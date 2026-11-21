import { useEffect } from 'react'
import { useFinishedJobs } from '../../shared/jobs/useJobs'
import { useXdeltaPatches } from './useXdeltaPatches'
import { useVaultBundles } from './useVaultBundles'

// Patches mode: xdelta patches (import, edit, create, build to ISO) and `.ssbm`
// bundles. Their builds, creations and installs are backend jobs that the
// hooks follow in the job store. Returns every patch and bundle state value
// and action in one object.
export function useVaultPatches({ fetchBundles }) {
  // XDelta patches hook
  const xdelta = useXdeltaPatches({ onBundleImportSuccess: fetchBundles })
  const { setShowXdeltaImportModal, installBundle } = xdelta

  // A bundle the export builder added (a `bundle_export` job) appears in the
  // grid as soon as its job is done, not on the next incidental re-fetch.
  const finishedBundleExports = useFinishedJobs('bundle_export')
  useEffect(() => {
    if (finishedBundleExports) fetchBundles?.()
  }, [finishedBundleExports])

  // `.ssbm` bundle actions on the Patches grid. Install progress shows in the
  // shared import modal, so the install itself is handed in.
  const bundleActions = useVaultBundles({
    fetchBundles,
    openImportModal: () => setShowXdeltaImportModal(true),
    installBundle,
  })

  return { ...xdelta, ...bundleActions }
}
