import { useState, useEffect, useCallback, useRef } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import ConfirmDialog from '../../shared/ui/ConfirmDialog'
import InGameTestPanel from '../../shared/viewer/InGameTestPanel'
import { useInGameTest } from '../hooks/useInGameTest'
import { useEditModal } from '../hooks/useEditModal'
import { useCspManager } from '../hooks/useCspManager'
import { useCharacterAudio } from '../hooks/useCharacterAudio'
import { useCostumeSkinDnd } from '../hooks/useCostumeSkinDnd'
import { useClickOutside } from '../../shared/hooks/useClickOutside'
import EditModal from '../EditModal'
import CspManagerModal from '../CspManagerModal'
import PoseManagerModal from './poses/PoseManagerModal'
import SoundBankModal from '../sounds/SoundBankModal'
import EmbeddedModelViewer from '../../shared/viewer/EmbeddedModelViewer'
import SkinCreator from '../editors/SkinCreator'
import { resolveBaseCharacter } from '../lib/customCharacter'
import SeriesPicker from './custom/CharacterSeriesSection'
import CustomCharacterTopBar from './custom/CustomCharacterTopBar'
import CustomCharacterHeader from './custom/CustomCharacterHeader'
import CustomCostumesSection from './custom/CustomCostumesSection'
import CustomSkinsSection from './custom/CustomSkinsSection'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

export default function CustomCharacterDetailView({
  character,
  onBack,
  onDelete,
  onRename,
  onSkinCreatorChange,
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState(character.name)
  const [saving, setSaving] = useState(false)
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [detail, setDetail] = useState(null)
  const [showSeriesPicker, setShowSeriesPicker] = useState(false)
  const [skinMessage, setSkinMessage] = useState('')
  const [importingSkin, setImportingSkin] = useState(false)
  const [seriesIconBust, setSeriesIconBust] = useState(0)
  const [assetBust, setAssetBust] = useState(0)
  const [poseList, setPoseList] = useState([])                   // saved poses for the default-pose picker
  const [applyingDefaultPose, setApplyingDefaultPose] = useState(false)
  const [renamingCostume, setRenamingCostume] = useState(null)  // { index, value }
  const { playingAudio, toggleAudio } = useCharacterAudio(character.slug)
  const [skinCreatorCostume, setSkinCreatorCostume] = useState(null) // opens SkinCreator on this skin
  const [showPoseManager, setShowPoseManager] = useState(false)
  const [showSoundBank, setShowSoundBank] = useState(false)
  const [selectedTeamColor, setSelectedTeamColor] = useState(null)   // armed team token ('red'|'blue'|'green')
  const [showDefaultPoseMenu, setShowDefaultPoseMenu] = useState(false)
  const skinFileRef = useRef(null)
  const iconFileRef = useRef(null)
  const bannerBigRef = useRef(null)
  const bannerSmallRef = useRef(null)
  const defaultPoseMenuRef = useRef(null)
  const inGameTest = useInGameTest()

  const fetchDetail = useCallback(async () => {
    try {
      const data = await api.get(`/custom-characters/${character.slug}/detail`)
      setDetail(data.detail)
    } catch (err) {
      console.error('Failed to fetch character detail:', err)
    }
  }, [character.slug, API_URL])

  useEffect(() => { fetchDetail() }, [fetchDetail])

  const baseCharacter = resolveBaseCharacter(detail?.based_on)

  useClickOutside(defaultPoseMenuRef, showDefaultPoseMenu, () => setShowDefaultPoseMenu(false))

  // ── Shared skin-editing stack (same modal as canonical character skins).
  // Custom skins are exposed to it under a pseudo-character key whose
  // path maps straight to this character's skins directory.
  const pseudoCharacter = `custom_characters/${character.slug}/skins`
  const setEditingItemRef = useRef(null)

  const cspManager = useCspManager({
    onRefresh: fetchDetail,
    onUpdateEditingItemAlts: (updater) => {
      setEditingItemRef.current?.(prev => prev ? {
        ...prev,
        data: {
          ...prev.data,
          alternateCsps: typeof updater === 'function'
            ? updater(prev.data.alternateCsps || [])
            : updater
        }
      } : prev)
    },
    onUpdateEditingItemActiveCsp: (activeCspId) => {
      setEditingItemRef.current?.(prev => prev ? {
        ...prev,
        data: { ...prev.data, active_csp_id: activeCspId }
      } : prev)
    },
    onUpdateEditingItemData: (updatedData) => {
      setEditingItemRef.current?.(prev => (
        prev?.type === 'costume' &&
        prev.data.id === updatedData.id &&
        prev.data.character === updatedData.character
          ? { ...prev, data: { ...prev.data, ...updatedData } }
          : prev
      ))
    }
  })

  const editModal = useEditModal({
    onRefresh: fetchDetail,
    fetchStageVariants: async () => {},
    setLastImageUpdate: cspManager.setLastImageUpdate
  })
  setEditingItemRef.current = editModal.setEditingItem

  // Bundled costumes are mirrored by the backend into an editable library
  // under this second pseudo key (materialized zips, folded back at install)
  const pseudoCostumes = `custom_characters/${character.slug}/costumes`

  const openSkinEditorFor = (charKey, skin) => {
    const base = API_URL.replace('/api/mex', '')
    editModal.handleEditClick('costume', {
      id: skin.id,
      character: charKey,
      color: skin.name || skin.color,
      dat_name: skin.dat_name || skin.dat,
      has_csp: skin.has_csp,
      has_stock: skin.has_stock,
      cspUrl: `${base}/storage/${charKey}/${skin.csp_filename || `${skin.id}_csp.png`}`,
      hdCspUrl: skin.has_hd_csp
        ? `${base}/storage/${charKey}/${skin.hd_csp_filename || `${skin.id}_csp_hd.png`}`
        : null,
      stockUrl: skin.has_stock ? `${base}/storage/${charKey}/${skin.id}_stc.png` : null,
      slippi_safe: skin.slippi_safe,
      slippi_tested: skin.slippi_tested,
      slippi_manual_override: skin.slippi_manual_override,
      has_hd_csp: skin.has_hd_csp,
      hd_csp_resolution: skin.hd_csp_resolution,
      hd_csp_size: skin.hd_csp_size,
      csp_pose_name: skin.csp_pose_name,
      active_csp_id: skin.active_csp_id || null,
      alternateCsps: (skin.alternate_csps || []).map(alt => ({
        id: alt.id,
        url: `${base}/storage/${charKey}/${alt.filename}`,
        poseName: alt.pose_name,
        isHd: alt.is_hd,
        timestamp: alt.timestamp
      }))
    })
  }

  const openSkinEditor = (skin) => openSkinEditorFor(pseudoCharacter, skin)
  const openCostumeEditor = (costume) => {
    if (!costume.edit_id) return
    openSkinEditorFor(pseudoCostumes, { ...costume, id: costume.edit_id })
  }

  // Edit Textures: open the shared SkinCreator on this skin. Saving creates a
  // NEW entry in this character's Custom Skins (SkinCreator routes the save by
  // the pseudo-character key).
  const handleStartSkinCreator = (itemData) => {
    editModal.handleCancel()
    setSkinCreatorCostume({
      id: itemData.id,
      character: itemData.character,
      color: itemData.color,
      dat_name: itemData.dat_name,
    })
  }

  // Test in Game: build a temp ISO with this fighter + exactly this skin
  // (added skins are imported as an extra costume slot; bundled costumes are
  // selected by their slot index) and play a short match.
  const handleTestInGame = () => {
    const item = editModal.editingItem
    if (!item) return
    if (item.data.character?.endsWith('/costumes')) {
      const costume = (detail?.costumes || []).find(c => c.edit_id === item.data.id)
      inGameTest.startCustomCharacterSkinTest({
        slug: character.slug,
        costumeIndex: costume?.index ?? 0,
        colorName: item.data.color,
      })
    } else {
      inGameTest.startCustomCharacterSkinTest({
        slug: character.slug,
        skinId: item.data.id,
        colorName: item.data.color,
      })
    }
  }

  // The modal's Delete: a bundled costume must come out of fighter.zip via
  // the proper removal endpoint, not the skins-library delete
  const handleModalDelete = async () => {
    const item = editModal.editingItem
    if (item?.data?.character?.endsWith('/costumes')) {
      const costume = (detail?.costumes || []).find(c => c.edit_id === item.data.id)
      if (!costume) return
      if (!await appConfirm(`Remove costume "${costume.name}" from ${character.name}?`, {
        title: 'Remove Costume',
        confirmText: 'Remove',
      })) return
      api.post(`/custom-characters/${character.slug}/costumes/${costume.index}/remove`)
        .then(async () => {
          playSound('boop')
          editModal.handleCancel()
          await fetchDetail()
        })
        .catch(err => alert(err.message || 'Remove failed'))
    } else {
      editModal.handleDelete()
    }
  }

  const handleSlippiRetest = async () => {
    const item = editModal.editingItem
    if (!item) return
    try {
      const data = await api.post(`/storage/costumes/retest-slippi`, { character: item.data.character, skinId: item.data.id })
      playSound('boop')
      editModal.setEditingItem(prev => prev ? {
        ...prev,
        data: { ...prev.data, slippi_safe: data.slippi_safe, slippi_tested: true, slippi_manual_override: null }
      } : prev)
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Retest failed')
    }
  }

  const handleSlippiOverride = async (slippiSafe) => {
    const item = editModal.editingItem
    if (!item) return
    try {
      await api.post(`/storage/costumes/override-slippi`, { character: item.data.character, skinId: item.data.id, slippiSafe })
      playSound('boop')
      editModal.setEditingItem(prev => prev ? {
        ...prev,
        data: { ...prev.data, slippi_safe: slippiSafe, slippi_manual_override: true }
      } : prev)
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Override failed')
    }
  }

  const flashSkinMessage = (msg) => {
    setSkinMessage(msg)
    setTimeout(() => setSkinMessage(''), 4000)
  }

  const handleSaveRename = async () => {
    const trimmed = nameValue.trim()
    if (!trimmed || trimmed === character.name) {
      setEditingName(false)
      setNameValue(character.name)
      return
    }
    setSaving(true)
    try {
      await api.post(`/custom-characters/${character.slug}/rename`, { newName: trimmed })
      setEditingName(false)
      onRename({ ...character, name: trimmed })
    } catch (err) {
      alert(err.message || 'Rename failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.post(`/custom-characters/${character.slug}/delete`)
      onDelete()
    } catch (err) {
      alert(err.message || 'Delete failed')
    } finally {
      setDeleting(false)
      setShowConfirmDialog(false)
    }
  }

  const handleExport = () => {
    const link = document.createElement('a')
    link.href = backendMediaUrl(`${API_URL}/custom-characters/${character.slug}/export`)
    // Without `download` a click is a navigation, which the Electron shell
    // blocks for the backend origin (will-navigate), so nothing downloads.
    link.download = '' // keep the filename supplied by Content-Disposition
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // CSS icon + result banners — replaced inside fighter.zip so installs pick them up
  const handleReplaceAsset = async (which, e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(`/custom-characters/${character.slug}/replace-asset/${which}`, formData)
      playSound('newSkin')
      setAssetBust(Date.now())
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Replace failed')
    }
  }

  const handleToggleWallJump = async () => {
    if (!detail) return
    try {
      await api.post(`/custom-characters/${character.slug}/set-wall-jump`, { canWallJump: !detail.can_wall_jump })
      playSound('boop')
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Toggle failed')
    }
  }

  // Team color tokens: click a token to arm it, then click a costume card to
  // assign — same interaction as the install page's vanilla character panel.
  const handleTeamColorClick = (team) => {
    playSound('boop')
    setSelectedTeamColor(selectedTeamColor === team ? null : team)
  }

  const handleCostumeTeamAssign = async (index) => {
    if (!selectedTeamColor || !detail) return
    try {
      await api.post(`/custom-characters/${character.slug}/set-team-colors`, { [selectedTeamColor]: index })
      playSound('newSkin')
      setSelectedTeamColor(null)
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Set team color failed')
    }
  }

  const saveCostumeRename = async () => {
    const target = renamingCostume
    setRenamingCostume(null)
    if (!target) return
    const name = target.value.trim()
    if (!name) return
    try {
      await api.post(
        `/custom-characters/${character.slug}/costumes/${target.index}/rename`,
        { name }
      )
      playSound('boop')
      await fetchDetail()
    } catch (err) {
      alert(err.message || 'Rename failed')
    }
  }

  const handleImportSkin = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setImportingSkin(true)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', file.name.replace(/\.[^.]+$/, ''))
    try {
      const data = await api.post(`/custom-characters/${character.slug}/skins/add`, formData)
      playSound('newSkin')
      flashSkinMessage(`Added skin ${data.skin.name}`)
      await fetchDetail()
    } catch (err) {
      flashSkinMessage(`Add failed: ${err.message}`)
    } finally {
      setImportingSkin(false)
    }
  }

  // Load the char's saved poses for the default-pose picker
  useEffect(() => {
    let cancelled = false
    api.get(`/storage/poses/list/${encodeURIComponent(pseudoCostumes)}`)
      .then(d => { if (!cancelled) setPoseList(d.poses || []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [API_URL, pseudoCostumes])

  // Set the default CSP pose and re-render every costume + skin in it.
  const handleSetDefaultPose = async (poseName) => {
    if (!poseName || applyingDefaultPose) return
    setShowDefaultPoseMenu(false)
    setApplyingDefaultPose(true)
    try {
      const data = await api.post(`/custom-characters/${character.slug}/default-pose`, { poseName })
      playSound('camera')
      const filled = data.filled ?? data.rendered ?? 0
      flashSkinMessage(`Default pose set — filled ${filled} missing CSP${filled === 1 ? '' : 's'}`)
      await fetchDetail()
    } catch (err) {
      flashSkinMessage(`Set default pose failed: ${err.message}`)
    } finally {
      setApplyingDefaultPose(false)
    }
  }

  const hasIcon = detail ? detail.has_css_icon : character.has_css_icon
  const iconUrl = hasIcon
    ? backendMediaUrl(`/api/mex/custom-characters/${character.slug}/icon`, assetBust || undefined)
    : null

  const costumes = detail?.costumes || []
  const addedSkins = detail?.added_skins || []
  const {
    draggingCostume, setDraggingCostume,
    skinDropActive, setSkinDropActive,
    draggingSkinId, setDraggingSkinId,
    skinDragOverId, setSkinDragOverId,
    costumeDragOverId, setCostumeDragOverId,
    costumesDropActive, setCostumesDropActive,
    handleCostumeToSkin, handleSkinReorder, handleCostumeReorder, handleSkinToCostume,
  } = useCostumeSkinDnd({
    slug: character.slug,
    costumes,
    addedSkins,
    onRefresh: fetchDetail,
    flashSkinMessage,
  })
  const BACKEND_BASE = API_URL.replace('/api/mex', '')
  const bigBanner = detail?.zip_assets?.big_banner
  const smallBanner = detail?.zip_assets?.small_banner
  const selectedDefaultPose = poseList.find(p => p.name === detail?.default_pose) || null
  const defaultPoseButtonLabel = applyingDefaultPose
    ? 'Applying...'
    : selectedDefaultPose?.name || (poseList.length > 0
      ? 'Default pose...'
      : 'Default pose (create one in Manage Poses)')
  const customSeriesActive = detail?.custom_series?.active

  // Editable controls (toggles, audio, replaceable assets)
  const editCells = detail ? [
    {
      label: 'Wall Jump',
      content: (
        <button
          className={`char-info-toggle ${detail.can_wall_jump ? 'on' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={handleToggleWallJump}
          title="Toggle whether this character can wall jump"
        >
          {detail.can_wall_jump ? 'Yes' : 'No'}
        </button>
      )
    },
    detail.victory_theme_info?.available && {
      label: 'Victory Theme',
      content: (
        <span className="char-audio-row" title="Ported into your project on install">
          <button
            className={`char-audio-btn ${playingAudio === 'victory' ? 'playing' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => toggleAudio('victory')}
          >
            {playingAudio === 'victory' ? '⏸' : '▶'}
          </button>
          <span className="char-audio-name" title={detail.victory_theme_info.name}>
            {detail.victory_theme_info.name}
          </span>
        </span>
      )
    },
    detail.announcer_available && {
      label: 'Announcer',
      content: (
        <span className="char-audio-row">
          <button
            className={`char-audio-btn ${playingAudio === 'announcer' ? 'playing' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => toggleAudio('announcer')}
          >
            {playingAudio === 'announcer' ? '⏸' : '▶'}
          </button>
          <span className="char-audio-name">Play call</span>
        </span>
      )
    },
    detail.has_sound_pack && {
      label: 'Sound Bank',
      content: (
        <button
          className="char-info-toggle"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); setShowSoundBank(true) }}
          title="Browse, preview and replace this character's sounds"
        >
          🔊 Browse
        </button>
      )
    },
    smallBanner && {
      label: 'Small Banner',
      content: (
        <span
          className="char-info-banner"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); bannerSmallRef.current?.click() }}
          title="Small result banner (120x24) — click to replace"
        >
          <img
            src={backendMediaUrl(`${smallBanner.url}${assetBust ? `?v=${assetBust}` : ''}`)}
            alt="small banner"
          />
        </span>
      )
    },
  ].filter(Boolean) : []

  const sourceLabel = character.source === 'zip'
    ? 'Imported ZIP'
    : (character.source === 'builtin' || character.builtin ? 'Built-in' : 'ISO Scan')

  // Read-only facts (compact strip)
  const infoPairs = detail ? [
    ['Source', sourceLabel],
    ['Added', new Date(character.date_added).toLocaleDateString()],
    detail.based_on && ['Based On', detail.based_on],
    ['Costumes', `${costumes.length}${addedSkins.length ? ` + ${addedSkins.length} custom` : ''}`],
    detail.anim_count != null && ['Animations', detail.anim_count],
    detail.sound_bank != null && ['Sound Bank', detail.has_sound_pack ? `${detail.sound_bank} (custom)` : detail.sound_bank],
    !detail.victory_theme_info?.available && detail.victory_theme != null && ['Victory Theme', `#${detail.victory_theme}`],
    !detail.announcer_available && detail.announcer_call != null && ['Announcer Call', `#${detail.announcer_call}`],
    ['Kirby Cap', detail.has_kirby_cap ? 'Yes' : 'No'],
    detail.ending_movies > 0 && ['Ending Movies', detail.ending_movies],
    detail.files?.fighterDataPath && ['Fighter File', detail.files.fighterDataPath],
  ].filter(Boolean) : []

  const testActive = inGameTest.testingInGame || inGameTest.testResult || inGameTest.testError

  return (
    <div className="storage-viewer">
      <div className="character-detail">
        {/* ── Top bar: back + test CTA ── */}
        <CustomCharacterTopBar
          detail={detail}
          onBack={onBack}
          setShowPoseManager={setShowPoseManager}
          character={character}
          defaultPoseMenuRef={defaultPoseMenuRef}
          showDefaultPoseMenu={showDefaultPoseMenu}
          applyingDefaultPose={applyingDefaultPose}
          poseList={poseList}
          setShowDefaultPoseMenu={setShowDefaultPoseMenu}
          defaultPoseButtonLabel={defaultPoseButtonLabel}
          handleSetDefaultPose={handleSetDefaultPose}
          testActive={testActive}
          inGameTest={inGameTest}
        />

        {testActive && (
          <div className="ingame-test-stage">
            <InGameTestPanel
              test={inGameTest}
              onStart={() => inGameTest.startCustomCharacterTest({ slug: character.slug, name: character.name })}
            />
          </div>
        )}

        {/* ── Header: editable icon + name + franchise + result banner ── */}
        <CustomCharacterHeader
          iconFileRef={iconFileRef}
          iconUrl={iconUrl}
          character={character}
          handleReplaceAsset={handleReplaceAsset}
          editingName={editingName}
          nameValue={nameValue}
          setNameValue={setNameValue}
          handleSaveRename={handleSaveRename}
          setEditingName={setEditingName}
          saving={saving}
          detail={detail}
          BACKEND_BASE={BACKEND_BASE}
          seriesIconBust={seriesIconBust}
          showSeriesPicker={showSeriesPicker}
          setShowSeriesPicker={setShowSeriesPicker}
          fetchDetail={fetchDetail}
          bigBanner={bigBanner}
          bannerBigRef={bannerBigRef}
          assetBust={assetBust}
        />

        <SeriesPicker
          show={showSeriesPicker}
          slug={character.slug}
          detail={detail}
          backendBase={BACKEND_BASE}
          seriesIconBust={seriesIconBust}
          onClose={() => setShowSeriesPicker(false)}
          onIconBust={setSeriesIconBust}
          onRefresh={fetchDetail}
        />

        {/* ── Editable controls ── */}
        {detail && editCells.length > 0 && (
          <div className="char-edit-grid">
            {editCells.map((cell) => (
              <div key={cell.label} className="char-info-cell">
                <span className="char-info-label">{cell.label}</span>
                <span className="char-info-value">{cell.content}</span>
              </div>
            ))}
            <input
              ref={bannerSmallRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => handleReplaceAsset('small_banner', e)}
              style={{ display: 'none' }}
            />
          </div>
        )}

        {/* ── Read-only info strip ── */}
        {detail && (
          <div className="char-info-strip">
            {infoPairs.map(([label, value]) => (
              <span key={label} className="char-info-pair">
                <span className="char-strip-label">{label}</span>
                <span className="char-strip-value">{value}</span>
              </span>
            ))}
          </div>
        )}

        {/* ── Costumes (drop a custom skin here to promote it) ── */}
        {costumes.length > 0 && (
          <CustomCostumesSection
            costumes={costumes}
            draggingSkinId={draggingSkinId}
            costumesDropActive={costumesDropActive}
            setCostumesDropActive={setCostumesDropActive}
            handleSkinToCostume={handleSkinToCostume}
            detail={detail}
            selectedTeamColor={selectedTeamColor}
            handleTeamColorClick={handleTeamColorClick}
            draggingCostume={draggingCostume}
            costumeDragOverId={costumeDragOverId}
            renamingCostume={renamingCostume}
            handleCostumeTeamAssign={handleCostumeTeamAssign}
            setDraggingCostume={setDraggingCostume}
            setSkinDropActive={setSkinDropActive}
            setCostumeDragOverId={setCostumeDragOverId}
            handleCostumeReorder={handleCostumeReorder}
            cspManager={cspManager}
            openCostumeEditor={openCostumeEditor}
            setRenamingCostume={setRenamingCostume}
            saveCostumeRename={saveCostumeRename}
          />
        )}

        {/* ── Custom skins (drop zone for bundled costumes) ── */}
        <CustomSkinsSection
          draggingCostume={draggingCostume}
          skinDropActive={skinDropActive}
          setSkinDropActive={setSkinDropActive}
          handleCostumeToSkin={handleCostumeToSkin}
          character={character}
          baseCharacter={baseCharacter}
          BACKEND_BASE={BACKEND_BASE}
          fetchDetail={fetchDetail}
          flashSkinMessage={flashSkinMessage}
          addedSkins={addedSkins}
          draggingSkinId={draggingSkinId}
          skinDragOverId={skinDragOverId}
          setDraggingSkinId={setDraggingSkinId}
          setSkinDragOverId={setSkinDragOverId}
          handleSkinReorder={handleSkinReorder}
          cspManager={cspManager}
          openSkinEditor={openSkinEditor}
          importingSkin={importingSkin}
          skinFileRef={skinFileRef}
          handleImportSkin={handleImportSkin}
          skinMessage={skinMessage}
        />

        <div className="custom-stage-actions">
          <button
            className="intake-import-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleExport() }}
            title="Download this character as a re-importable ZIP"
          >
            Export ZIP
          </button>
          <button
            className="intake-import-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); setShowConfirmDialog(true) }}
            style={{ background: 'var(--color-danger, #e53e3e)' }}
            disabled={deleting}
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>

      <ConfirmDialog
        show={showConfirmDialog}
        title="Delete Custom Character"
        message={`Are you sure you want to delete "${character.name}"? This cannot be undone.`}
        confirmText="Delete"
        onConfirm={handleDelete}
        onCancel={() => setShowConfirmDialog(false)}
      />

      {/* ── Shared skin editing stack (same modal as canonical skins) ── */}
      <EditModal
        show={editModal.showEditModal}
        editingItem={editModal.editingItem}
        covered={Boolean(showConfirmDialog || skinCreatorCostume != null || editModal.show3DViewer
          || cspManager.showCspManager || showPoseManager || showSoundBank || editModal.showConfirmDialog)}
        editName={editModal.editName}
        onNameChange={editModal.setEditName}
        onRename={editModal.renameItem}
        renaming={editModal.renaming}
        busy={editModal.busy}
        deleting={editModal.deleting}
        exporting={editModal.exporting}
        lastImageUpdate={cspManager.lastImageUpdate}
        onClose={() => { inGameTest.resetTest(); editModal.handleCancel(); }}
        onDelete={handleModalDelete}
        onExport={editModal.handleExport}
        onReplaceStock={editModal.replaceStock}
        onGenerateStock={editModal.handleGenerateStock}
        onConfirmGeneratedStock={editModal.confirmGeneratedStock}
        onDiscardGeneratedStock={editModal.discardGeneratedStock}
        pendingGeneratedStock={editModal.pendingGeneratedStock}
        generatingStock={editModal.generatingStock}
        onSlippiRetest={handleSlippiRetest}
        onSlippiOverride={handleSlippiOverride}
        onOpenCspManager={cspManager.openCspManager}
        onStartSkinCreator={handleStartSkinCreator}
        onView3D={() => editModal.setShow3DViewer(true)}
        onTestInGame={handleTestInGame}
        testingInGame={inGameTest.testingInGame}
        testStatus={inGameTest.testStatus}
        testResult={inGameTest.testResult}
        testError={inGameTest.testError}
        testMode={inGameTest.testMode}
        stoppingTest={inGameTest.stoppingTest}
        stopError={inGameTest.stopError}
        onStopTest={inGameTest.stopTest}
        onResetTest={inGameTest.resetTest}
      />
      <SkinCreator
        isOpen={skinCreatorCostume != null}
        onClose={() => setSkinCreatorCostume(null)}
        selectedCharacter={character.name}
        onSkinCreatorChange={onSkinCreatorChange}
        onRefresh={fetchDetail}
        initialCostume={skinCreatorCostume}
      />
      {editModal.show3DViewer && editModal.editingItem?.type === 'costume' && (
        <EmbeddedModelViewer
          character={editModal.editingItem.data.character}
          skinId={editModal.editingItem.data.id}
          title={editModal.editingItem.data.color || editModal.editingItem.data.name}
          onClose={() => editModal.setShow3DViewer(false)}
        />
      )}
      <CspManagerModal
        show={cspManager.showCspManager}
        skin={cspManager.cspManagerSkin}
        portraits={cspManager.portraits}
        lastImageUpdate={cspManager.lastImageUpdate}
        busy={cspManager.busy}
        onClose={cspManager.closeCspManager}
        onSetActive={cspManager.handleSetActivePortrait}
        onRemove={cspManager.handleRemovePortrait}
        onReplaceOriginal={cspManager.handleUploadMainCsp}
        onAddPortrait={cspManager.handleUploadAltCsp}
        onOpenPoseManager={() => { cspManager.closeCspManager(); setShowPoseManager(true); }}
      />
      <PoseManagerModal
        show={showPoseManager}
        character={pseudoCostumes}
        displayName={character.name}
        baseSkinId={detail?.costumes?.[0]?.id}
        models={(detail?.costumes || []).map(c => ({
          value: c.id,
          label: c.color || c.name || c.id,
          skinId: c.id,
          cspUrl: c.csp_url,
          stockUrl: c.stock_url
        }))}
        onClose={() => setShowPoseManager(false)}
        onRefresh={fetchDetail}
        defaultPoseName={detail?.default_pose || ''}
        onSetDefaultPose={handleSetDefaultPose}
        settingDefaultPose={applyingDefaultPose}
      />
      <SoundBankModal
        show={showSoundBank}
        slug={character.slug}
        displayName={character.name}
        onClose={() => setShowSoundBank(false)}
      />
      <ConfirmDialog
        show={editModal.showConfirmDialog}
        title={editModal.confirmDialogData?.title}
        message={editModal.confirmDialogData?.message}
        confirmText={editModal.confirmDialogData?.confirmText}
        onConfirm={editModal.confirmDelete}
        onCancel={editModal.cancelDelete}
      />
    </div>
  )
}
