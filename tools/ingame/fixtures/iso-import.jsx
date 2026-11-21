import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import VaultImportSurface from '../../../app/frontend/src/vault/import/VaultImportSurface'

window.importedFiles = []
window.refreshCalls = 0
window.rejectRefresh = false

function ImportFixture() {
  const [paths, setPaths] = useState([])
  const [open, setOpen] = useState(false)
  return <VaultImportSurface
    importing={false}
    onFileImport={files => window.importedFiles.push(...files.map(file => file.name))}
    showIsoScanModal={open}
    scanInitialPaths={paths}
    onScanOpen={next => { setPaths(next); setOpen(true) }}
    onScanClose={() => { setOpen(false); setPaths([]) }}
    onRefresh={async () => { window.refreshCalls++; if (window.rejectRefresh) throw new Error('Refresh fixture failure') }}
  />
}

createRoot(document.getElementById('root')).render(<ImportFixture />)
