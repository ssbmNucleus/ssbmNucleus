import { useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import ConfirmDialog from '../shared/ui/ConfirmDialog'

export default function SetupSection({ onOpenFirstRunSetup }) {
  const [showConfirm, setShowConfirm] = useState(false)

  const handleOpenConfirm = () => {
    setShowConfirm(true)
  }

  const handleCancel = () => {
    setShowConfirm(false)
  }

  const handleConfirm = () => {
    setShowConfirm(false)
    onOpenFirstRunSetup()
  }

  return (
    <>
      <section className="settings-section">
        <h3>First-Time Setup</h3>
        <p className="section-description">
          Re-run the setup wizard to detect Slippi Dolphin again, verify your Melee ISO, and rebuild the vanilla asset bundle used by Nucleus.
        </p>

        <div className="setup-section-actions">
          <button
            className="restore-button setup-rerun-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleOpenConfirm(); }}
          >
            Run Setup Again
          </button>
        </div>

        <p className="setup-section-note">
          This refreshes extracted vanilla assets only. It does not clear your imported vault content.
        </p>
      </section>

      <ConfirmDialog
        show={showConfirm}
        title="Run First-Time Setup Again?"
        message="This will reopen the setup wizard and may overwrite extracted vanilla asset files with a fresh copy from your Melee ISO."
        confirmText="Run Setup"
        cancelText="Keep Current Setup"
        confirmStyle="primary"
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </>
  )
}
