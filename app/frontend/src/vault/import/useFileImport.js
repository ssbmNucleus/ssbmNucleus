/**
 * useFileImport Hook — the one import pipeline for the whole vault.
 *
 * Feeds files (from the floating Import button, drag-and-drop, or any legacy
 * input) to the backend's unified /import/file endpoint, which auto-detects
 * costumes, stages, custom characters, custom stages (incl. classic stage.yml
 * packages), bundles, xdelta patches, menu mods (icon grids, backgrounds,
 * doors, pause screens, HUD typefaces — compiled files OR loose pictures),
 * and effect files for a character's Extras. Handles:
 * - Slippi safety dialog (single file) / auto-fix (batch)
 * - Duplicate dialog (single file) / auto-skip (batch)
 * - "What is this?" choice dialog for ambiguous uploads (single) / the
 *   backend's default pick (batch)
 * - type-aware refresh of whichever vault list the import landed in
 * - import success/error messages (backend messages are user-ready)
 *
 * An import UNIT is one request: normally one file, but several loose
 * pictures picked together (the ten digits of a glyph pack, a batch of door
 * textures) go up as one multi-file request so detection sees them as a set.
 */

import { useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

// What each successful import type means for UI refresh + summary counting.
const TYPE_LABELS = {
  character: 'costume(s)',
  stage: 'stage variant(s)',
  custom_character: 'custom character(s)',
  custom_stage: 'custom stage(s)',
  bundle: 'bundle(s)',
  patch: 'patch(es)',
  menu_mod: 'menu mod(s)',
  effect: 'effect(s)',
}

const isImage = (file) => /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name)

// Group a selection into request units: loose pictures picked together
// travel as one unit; everything else is one unit per file.
const toUnits = (files) => {
  if (files.length > 1 && files.every(isImage)) return [files]
  return files.map((f) => [f])
}

const unitName = (unit) => unit.length === 1 ? unit[0].name : `${unit.length} pictures`

export function useFileImport({
  refreshers = {}
}) {
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')
  const [showSlippiDialog, setShowSlippiDialog] = useState(false)
  const [slippiDialogData, setSlippiDialogData] = useState(null)
  const [pendingFile, setPendingFile] = useState(null)   // the pending UNIT (array of Files)
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false)
  const [duplicateDialogData, setDuplicateDialogData] = useState(null)
  const [showChoiceDialog, setShowChoiceDialog] = useState(false)
  const [choiceDialogData, setChoiceDialogData] = useState(null)
  // Slippi/duplicate/choice answers already given for the pending single
  // import, carried across dialogs when an upload trips more than one gate.
  const [pendingActions, setPendingActions] = useState({})

  const importUnit = async (unit, { slippiAction = null, duplicateAction = null, hints = null } = {}) => {
    const formData = new FormData()
    for (const file of unit) formData.append('file', file)
    if (slippiAction) formData.append('slippi_action', slippiAction)
    if (duplicateAction) formData.append('duplicate_action', duplicateAction)
    for (const [key, value] of Object.entries(hints || {})) {
      if (value != null) formData.append(key, value)
    }

    // Let the backend capture an in-game screenshot for stage variants that
    // ship without one (background job; needs the ISO + Dolphin to boot).
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')
    const slippiDolphinPath = localStorage.getItem('slippi_dolphin_path')
    if (vanillaIsoPath) formData.append('vanillaIsoPath', vanillaIsoPath)
    if (slippiDolphinPath) formData.append('slippiDolphinPath', slippiDolphinPath)

    try {
      return await api.post('/import/file', formData)
    } catch (err) {
      // The unified importer answers the slippi/duplicate/choice dialogs (and
      // plain failures) with a { success: false, type, error } envelope, which
      // the api client turns into a thrown ApiError. Every caller below
      // branches on that body itself, so hand it back instead of throwing.
      if (err.data) return err.data
      throw err
    }
  }

  const defaultChoiceHints = (data) =>
    (data.options || []).find((o) => o.key === data.default)?.hints
    || data.options?.[0]?.hints
    || null

  // Batch imports answer dialogs automatically the way a user almost always
  // would: fix Slippi issues, skip owned duplicates (per-costume — the
  // backend filters the owned entries and imports the rest of the zip), and
  // take the backend's default for an ambiguous upload. Loop because one file
  // can trip more than one gate.
  const importWithAutoAnswers = async (unit) => {
    const actions = {}
    for (let attempt = 0; attempt < 4; attempt++) {
      const data = await importUnit(unit, actions)
      if (data.type === 'slippi_dialog' && !actions.slippiAction) {
        actions.slippiAction = 'fix'
        continue
      }
      if (data.type === 'duplicate_dialog' && !actions.duplicateAction) {
        actions.duplicateAction = 'skip'
        continue
      }
      if (data.type === 'choice_dialog' && !actions.hints) {
        actions.hints = defaultChoiceHints(data)
        if (actions.hints) continue
      }
      return data
    }
    return { success: false, error: 'import kept requesting user input' }
  }

  // Refresh whichever lists the imported types touch (each at most once).
  const refreshForTypes = async (types) => {
    await refreshers.metadata?.()
    if (types.has('stage')) await refreshers.stageVariants?.()
    if (types.has('custom_character')) await refreshers.customCharacters?.()
    if (types.has('custom_stage')) await refreshers.customStages?.()
    if (types.has('patch')) await refreshers.patches?.()
    if (types.has('bundle')) await refreshers.bundles?.()
    if (types.has('menu_mod')) await refreshers.menuMods?.()
    if (types.has('effect')) await refreshers.extras?.()
  }

  const countItems = (data) =>
    data.imported_count
    ?? (data.patches?.length || data.mods?.length)
    ?? 1

  const successMessage = (data) => {
    // The backend's messages are user-ready ("Imported custom stage: X
    // (converted from classic m-ex format)", "Imported 2 door texture(s): …
    // — Menus › Character Select › Doors", ...) so prefer them.
    if (data.message) return `✓ ${data.message}`
    const label = TYPE_LABELS[data.type] || 'item(s)'
    return `✓ Imported ${countItems(data)} ${label}`
  }

  const finishSoon = (delay = 3000) => {
    setTimeout(() => {
      setImporting(false)
      setImportMessage('')
    }, delay)
  }

  // Accepts a DOM change event, a FileList, or an array of Files.
  const normalizeFiles = (eventOrFiles) => {
    if (!eventOrFiles) return []
    if (eventOrFiles.target?.files) return Array.from(eventOrFiles.target.files)
    if (typeof eventOrFiles.length === 'number') return Array.from(eventOrFiles)
    return []
  }

  // Park a single-unit import on a dialog and hand control to the user.
  const parkOnDialog = (data, unit, actions, eventOrFiles) => {
    if (data.type === 'slippi_dialog') {
      setSlippiDialogData(data)
      setShowSlippiDialog(true)
    } else if (data.type === 'duplicate_dialog') {
      setDuplicateDialogData(data)
      setShowDuplicateDialog(true)
    } else {
      setChoiceDialogData(data)
      setShowChoiceDialog(true)
    }
    setPendingFile(unit)
    setPendingActions(actions)
    setImporting(false)
    setImportMessage('')
    if (eventOrFiles?.target) eventOrFiles.target.value = null
  }

  const isDialog = (data) =>
    data.type === 'slippi_dialog' || data.type === 'duplicate_dialog' || data.type === 'choice_dialog'

  const handleFileImport = async (eventOrFiles) => {
    const files = normalizeFiles(eventOrFiles)
    if (files.length === 0) return
    setPendingActions({})

    const units = toUnits(files)
    setImporting(true)
    let successCount = 0
    let errorCount = 0
    let totalItems = 0
    let skippedCount = 0
    const skippedDuplicates = []
    let fixedCount = 0
    let cameraSoundCount = 0
    let lastError = null
    let lastSuccess = null
    const failures = []
    const importedTypes = new Set()

    for (let i = 0; i < units.length; i++) {
      const unit = units[i]
      setImportMessage(units.length === 1
        ? `Importing ${unitName(unit)}...`
        : `Importing ${i + 1}/${units.length}: ${unitName(unit)}...`)

      try {
        // Single-unit imports surface the dialogs for the user to answer;
        // batch imports auto-answer them (fix / skip / default kind).
        const data = units.length === 1
          ? await importUnit(unit)
          : await importWithAutoAnswers(unit)

        if (units.length === 1 && isDialog(data)) {
          parkOnDialog(data, unit, {}, eventOrFiles)
          return
        }

        if (data.success) {
          successCount++
          totalItems += countItems(data)
          skippedCount += data.skipped_count || 0
          skippedDuplicates.push(...(data.skipped_duplicates || []))
          fixedCount += data.fixed_count || 0
          ;(data.types || [data.type]).forEach(t => importedTypes.add(t))
          lastSuccess = data
          if (data.camera_sound) cameraSoundCount++
          // Container zips report per-inner-file failures alongside success.
          for (const f of data.failed || []) {
            failures.push(`${f.name}: ${f.error}`)
          }
        } else {
          errorCount++
          lastError = data.error
          failures.push(`${unitName(unit)}: ${data.error || 'import failed'}`)
        }
      } catch (err) {
        errorCount++
        lastError = err.message
        failures.push(`${unitName(unit)}: ${err.message}`)
      }
    }

    await refreshForTypes(importedTypes)

    if (successCount > 0) {
      playSound(cameraSoundCount > 0 ? 'camera' : 'newSkin')
    }
    if (errorCount > 0 && successCount === 0) {
      playSound('error')
    }

    // Every file that didn't make it in, with the reason — the toast only has
    // room for a count, so the details go to the console for support.
    if (failures.length) {
      console.warn(`[import] ${failures.length} file(s) not imported:\n` + failures.join('\n'))
    }

    // Summary. Single unit: the backend message (or specific error) verbatim.
    // Batch: counts by what actually happened.
    let summary
    if (units.length === 1) {
      summary = successCount
        ? successMessage(lastSuccess)
        : skippedCount
          ? 'Skipped (already owned)'
          : `✗ ${lastError || 'Import failed'}`
    } else {
      const typeBreakdown = [...importedTypes]
        .filter(t => t && t !== 'multi')
        .map(t => TYPE_LABELS[t] || t).join(', ')
      const parts = [`✓ Imported ${totalItems} item(s) from ${successCount} file(s)`]
      if (typeBreakdown) parts.push(`(${typeBreakdown})`)
      if (fixedCount) parts.push(`· ${fixedCount} auto-fixed for Slippi`)
      if (skippedCount) parts.push(`· ${skippedCount} skipped, already owned`)
      if (failures.length) parts.push(`· ${failures.length} not imported${lastError ? `: ${lastError}` : ''}`)
      summary = successCount === 0 && errorCount > 0
        ? `✗ ${errorCount} failed${lastError ? `: ${lastError}` : ''}`
        : parts.join(' ')
    }
    setImportMessage(summary)
    if (skippedDuplicates.length) {
      setDuplicateDialogData({
        type: 'skipped_summary',
        skipped_count: skippedCount,
        duplicate_skins: skippedDuplicates,
      })
      setShowDuplicateDialog(true)
    }
    finishSoon(failures.length > 0 ? 6000 : 3500)

    // Reset file input
    if (eventOrFiles?.target) eventOrFiles.target.value = null
  }

  // Re-run a single import after a dialog choice, carrying forward every
  // answer already given. An upload can trip several gates (a duplicate
  // that's also not Slippi-safe; an ambiguous picture that turns out to be a
  // duplicate): answering one dialog then surfaces the next as a fresh
  // {type, success:false} response. Re-show that dialog instead of rendering
  // it as "Import failed: undefined" (the old bug). Mirrors useDownloadQueue.
  const continueImport = async (unit, actions) => {
    if (!unit) return
    setImporting(true)
    setImportMessage('Importing...')
    try {
      const data = await importUnit(unit, actions)

      if (isDialog(data)) {
        parkOnDialog(data, unit, actions)
        return
      }

      if (data.success) {
        playSound(data.camera_sound ? 'camera' : 'newSkin')
        setImportMessage(successMessage(data))
        await refreshForTypes(new Set(data.types || [data.type]))
      } else {
        playSound('error')
        setImportMessage(`✗ Import failed: ${data.error || 'Unknown error'}`)
      }
    } catch (err) {
      playSound('error')
      setImportMessage(`✗ Error: ${err.message}`)
    }
    setPendingFile(null)
    setPendingActions({})
    finishSoon(2000)
  }

  const handleSlippiChoice = (choice) => {
    setShowSlippiDialog(false)
    setSlippiDialogData(null)
    const unit = pendingFile
    const actions = pendingActions
    if (choice === 'cancel') {
      setPendingFile(null)
      setPendingActions({})
      return
    }
    continueImport(unit, { ...actions, slippiAction: choice })
  }

  const handleDuplicateChoice = (choice) => {
    const isSkippedSummary = duplicateDialogData?.type === 'skipped_summary'
    setShowDuplicateDialog(false)
    setDuplicateDialogData(null)
    const unit = pendingFile
    const actions = pendingActions
    if (isSkippedSummary) {
      setPendingFile(null)
      setPendingActions({})
      return
    }
    if (choice !== 'import_anyway') {
      // Costume, stage, and patch ZIPs can all contain multiple importable
      // items. Let the backend filter owned entries and import the rest.
      continueImport(unit, { ...actions, duplicateAction: 'skip' })
      return
    }
    continueImport(unit, { ...actions, duplicateAction: 'import_anyway' })
  }

  // The "What is this?" answer: re-send with the chosen option's hints.
  const handleChoice = (optionKey) => {
    const data = choiceDialogData
    setShowChoiceDialog(false)
    setChoiceDialogData(null)
    const unit = pendingFile
    const actions = pendingActions
    const option = (data?.options || []).find((o) => o.key === optionKey)
    if (!option) {
      setPendingFile(null)
      setPendingActions({})
      return
    }
    continueImport(unit, { ...actions, hints: option.hints })
  }

  return {
    // State
    importing,
    importMessage,
    showSlippiDialog,
    setShowSlippiDialog,
    slippiDialogData,
    setSlippiDialogData,
    pendingFile,
    setPendingFile,
    showDuplicateDialog,
    duplicateDialogData,
    showChoiceDialog,
    choiceDialogData,

    // Handlers
    handleFileImport,
    handleSlippiChoice,
    handleDuplicateChoice,
    handleChoice
  }
}
