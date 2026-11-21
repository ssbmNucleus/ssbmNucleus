import XdeltaImportModal from './XdeltaImportModal'
import XdeltaEditModal from './XdeltaEditModal'
import XdeltaCreateModal from '../../projects/export/XdeltaCreateModal'
import BundleEditModal from './BundleEditModal'
import { BACKEND_URL } from '../../shared/config/config'

// The Patches dialogs on the Vault home page: import (patches and bundles),
// edit patch, edit bundle, and create patch. `patches` is useVaultPatches().
export default function PatchModals({ patches }) {
  const {
    showXdeltaImportModal, xdeltaImportData, setXdeltaImportData, importingXdelta, handleImportXdelta,
    closeXdeltaImportModal, bundlePreview, bundleImporting, bundleProgress, bundleMessage,
    bundleComplete, bundleError, bundleResult, handleBundleImport, handleBundlePreview,
    handleBundleReset, showXdeltaEditModal, editingXdelta, setEditingXdelta, handleSaveXdeltaEdit,
    setShowXdeltaEditModal, handleDeleteXdelta, handleUpdateXdeltaImage, handleDownloadPatch, showBundleEditModal,
    editingBundle, setEditingBundle, handleSaveBundleEdit, setShowBundleEditModal, handleDeleteBundle,
    handleUpdateBundleImage, handleDownloadBundle, showXdeltaCreateModal, xdeltaCreateState, xdeltaCreateData,
    setXdeltaCreateData, xdeltaCreateProgress, xdeltaCreateMessage, xdeltaCreateError, xdeltaCreateResult,
    closeXdeltaCreateModal, handleSelectModdedIso, handleStartCreateXdelta,
  } = patches

  return (
    <>
      {/* XDelta Import Modal */}
      <XdeltaImportModal
        show={showXdeltaImportModal}
        importData={xdeltaImportData}
        onImportDataChange={setXdeltaImportData}
        importing={importingXdelta}
        onImport={handleImportXdelta}
        onCancel={closeXdeltaImportModal}
        // Bundle props
        bundlePreview={bundlePreview}
        bundleImporting={bundleImporting}
        bundleProgress={bundleProgress}
        bundleMessage={bundleMessage}
        bundleComplete={bundleComplete}
        bundleError={bundleError}
        bundleResult={bundleResult}
        onBundleImport={handleBundleImport}
        onBundlePreview={handleBundlePreview}
        onBundleReset={handleBundleReset}
      />

      {/* XDelta Edit Modal */}
      <XdeltaEditModal
        show={showXdeltaEditModal}
        patch={editingXdelta}
        onPatchChange={setEditingXdelta}
        onSave={handleSaveXdeltaEdit}
        onCancel={() => {
          setShowXdeltaEditModal(false)
          setEditingXdelta(null)
        }}
        onDelete={handleDeleteXdelta}
        onUpdateImage={handleUpdateXdeltaImage}
        onDownload={handleDownloadPatch}
        BACKEND_URL={BACKEND_URL}
      />

      {/* Bundle Edit Modal */}
      <BundleEditModal
        show={showBundleEditModal}
        bundle={editingBundle}
        onBundleChange={setEditingBundle}
        onSave={handleSaveBundleEdit}
        onCancel={() => {
          setShowBundleEditModal(false)
          setEditingBundle(null)
        }}
        onDelete={handleDeleteBundle}
        onUpdateImage={handleUpdateBundleImage}
        onDownload={handleDownloadBundle}
        BACKEND_URL={BACKEND_URL}
      />

      {/* XDelta Create Patch Modal */}
      <XdeltaCreateModal
        show={showXdeltaCreateModal}
        xdeltaCreateState={xdeltaCreateState}
        xdeltaCreateData={xdeltaCreateData}
        setXdeltaCreateData={setXdeltaCreateData}
        xdeltaCreateProgress={xdeltaCreateProgress}
        xdeltaCreateMessage={xdeltaCreateMessage}
        xdeltaCreateError={xdeltaCreateError}
        xdeltaCreateResult={xdeltaCreateResult}
        onClose={closeXdeltaCreateModal}
        onSelectModdedIso={handleSelectModdedIso}
        onStartCreate={handleStartCreateXdelta}
        onDownloadPatch={handleDownloadPatch}
      />
    </>
  )
}
