import { useState } from 'react'
import ImportFab from './ImportFab'
import IsoScanModal from './IsoScanModal'

/**
 * VaultImportSurface - the one import affordance of the vault: the floating
 * Import button (bottom-right) plus its drop-anywhere overlay, and the ISO
 * scan modal it opens.
 *
 * ISO/GCM files split off into the ISO scan modal (the preload resolves
 * their local paths); everything else goes to /import/file via
 * onFileImport.
 *
 * The scan-modal open state is CONTROLLED by the parent (StorageViewer):
 * this element is rendered in a different slot per vault branch, so owning
 * the state here would let a branch change unmount the open modal and drop
 * the selected ISO paths.
 */
export default function VaultImportSurface({
  importing,
  importMessage,
  onFileImport,
  onRefresh,
  onCustomCharactersChanged,
  onCustomStagesChanged,
  showIsoScanModal,
  scanInitialPaths,
  onScanOpen,
  onScanClose
}) {
  const [isoPathError, setIsoPathError] = useState(null)

  const handleImportOrScan = (files) => {
    const isIso = (f) => /\.(iso|gcm)$/i.test(f.name)
    const isos = files.filter(isIso)
    const rest = files.filter(f => !isIso(f))
    if (isos.length) {
      const paths = []
      const unreadable = []
      for (const file of isos) {
        try {
          const path = window.electron?.getPathForFile(file)
          if (path) {
            paths.push(path)
            continue
          }
        } catch { /* Show a recovery action instead of dropping the selection. */ }
        unreadable.push(file.name)
      }
      setIsoPathError(unreadable.length
        ? (window.electron?.openIsoMultiDialog
            ? `Could not open ${unreadable.join(', ')}. Try Add ISOs.`
            : 'Open the Nucleus desktop app to scan ISOs.')
        : null)
      onScanOpen(paths)
    }
    if (rest.length) onFileImport(rest)
  }

  return (
    <>
      <ImportFab
        importing={importing}
        importMessage={importMessage}
        onImportFiles={handleImportOrScan}
      />
      {showIsoScanModal && (
        <IsoScanModal
          initialIsoPaths={scanInitialPaths}
          initialPathError={isoPathError}
          onClose={onScanClose}
          onRefresh={onRefresh}
          onCustomCharactersChanged={onCustomCharactersChanged}
          onCustomStagesChanged={onCustomStagesChanged}
        />
      )}
    </>
  )
}
