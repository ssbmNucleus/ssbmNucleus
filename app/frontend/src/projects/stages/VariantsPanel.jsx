/**
 * VariantsPanel - DAS variant view of StageMode for the selected stage:
 * variants in the ISO (with button token assignment/removal) and storage
 * variants available to import (with batch controls).
 */
import { useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { BACKEND_URL, backendMediaUrl } from '../../shared/config/config'
import PaginationBar from '../../shared/ui/PaginationBar'
import usePagination from '../../shared/hooks/usePagination'
import StageMusicModal from '../StageMusicModal'

const MusicIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M9 18V5l12-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </svg>
)

export default function VariantsPanel({ sm }) {
  const { selectedStage, mexVariants, dataReady } = sm
  const availableVariants = sm.getVariantsForStage(selectedStage.code)
  const hasVanilla = mexVariants.some(variant =>
    variant.filename?.toLowerCase() === 'vanilla.dat')
  const inIsoPager = usePagination(mexVariants.length, `${selectedStage.code}-iso`)
  const availPager = usePagination(availableVariants.length, `${selectedStage.code}-avail`)

  // Stage music editor (this stage's weighted playlist in the open project)
  const [showStageMusic, setShowStageMusic] = useState(false)

  // Button Tokens Component
  const ButtonTokens = () => {
    const buttons = ['B', 'X', 'Y', 'L', 'R', 'Z']

    return (
      <div className="button-tokens">
        {buttons.map(btn => (
          <div
            key={btn}
            className={`button-token ${sm.selectedButton === btn ? 'selected' : ''}`}
            onClick={() => sm.handleButtonClick(btn)}
            title={sm.selectedButton === btn ? `Click to deselect ${btn} button` : `Click to select ${btn} button`}
          >
            <img src={backendMediaUrl(`/utility/buttons/${btn}.svg`)} alt={btn} />
          </div>
        ))}
      </div>
    )
  }

  return (
    <>
      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            In ISO ({dataReady ? mexVariants.length : 'Loading...'})
            {sm.selectedInstalledVariants.size > 0 && ` - ${sm.selectedInstalledVariants.size} selected`}
          </h3>
          <div className="iso-mod-actions">
            {mexVariants.length > 0 && (
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); sm.selectAllInstalledVariants(); }}
                disabled={!dataReady || sm.removing || sm.selectedButton}
              >
                Select All
              </button>
            )}
            {sm.selectedInstalledVariants.size > 0 && (
              <>
                <button
                  className="btn-batch-import btn-batch-delete"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); sm.handleBatchRemoveVariants(); }}
                  disabled={sm.removing || sm.selectedButton}
                >
                  Delete Selected ({sm.selectedInstalledVariants.size})
                </button>
                <button
                  className="btn-clear-selection"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); sm.clearInstalledVariantSelection(); }}
                  disabled={sm.removing}
                >
                  Clear
                </button>
              </>
            )}
            {dataReady && !hasVanilla && (
              <button
                className="btn-extras-mode"
                onClick={() => { playSound('start'); sm.handleRestoreVanilla(); }}
                onMouseEnter={playHoverSound}
                disabled={sm.restoringVanilla || sm.removing}
                title="Add the original stage from your vanilla ISO"
              >
                {sm.restoringVanilla ? 'Adding...' : 'Add Vanilla'}
              </button>
            )}
            <button
              className="btn-pose-all btn-sound-pack"
              onClick={() => { playSound('boop'); setShowStageMusic(true); }}
              onMouseEnter={playHoverSound}
              title="Stage music — choose which songs this stage plays in this project"
            >
              <MusicIcon />
            </button>
          </div>
          <ButtonTokens />
        </div>
        {sm.dasMissingStages.includes(selectedStage.code) && (
          // DAS was set up, but this stage's loader could not be made (no
          // vanilla copy of its stage file was found): offer the install again.
          <div className="transform-fix-notice warning" role="alert">
            <div className="transform-fix-notice-copy">
              <strong>No alternate-stage loader for {selectedStage.name}</strong>
              <span>
                The game ignores this stage's variants until its loader is installed. The loader is
                made from the stage file in your own Melee 1.02 ISO: set your vanilla ISO in Settings,
                then install again.
              </span>
            </div>
            <button
              type="button"
              className="btn-extras-mode"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); sm.installDAS(); }}
              disabled={sm.dasChecking}
            >
              {sm.dasChecking ? 'Installing...' : 'Install Again'}
            </button>
          </div>
        )}
        <div className="costume-list existing">
          {mexVariants.slice(inIsoPager.start, inIsoPager.end).map((variant, i) => {
            const idx = inIsoPager.start + i
            const isVanilla = variant.filename?.startsWith('vanilla')
            const imageUrl = isVanilla
              ? selectedStage.vanillaImage
              : (variant.screenshotUrl ? `${BACKEND_URL}${variant.screenshotUrl}` : null)
            const hasImage = isVanilla ? true : variant.hasScreenshot
            const canAssignButton = sm.selectedButton && variant.button !== sm.selectedButton
            const isDeleteSelected = sm.selectedInstalledVariants.has(sm.installedVariantKey(selectedStage.code, variant.name))

            return (
              <div
                key={idx}
                className={`costume-card existing-costume ${isDeleteSelected ? 'selected' : ''} ${canAssignButton ? 'button-assignable' : ''} ${dataReady ? 'card-visible' : 'card-hidden'}`}
                onMouseEnter={playHoverSound}
                onClick={() => sm.handleVariantClick(variant)}
                style={{ cursor: canAssignButton ? 'pointer' : 'default', animationDelay: dataReady ? `${Math.min(i * 30, 990)}ms` : '0ms' }}
              >
                <div className="costume-preview">
                  <input
                    type="checkbox"
                    className="costume-checkbox"
                    checked={isDeleteSelected}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => { playSound('boop'); sm.toggleInstalledVariantSelection(selectedStage.code, variant.name); }}
                    disabled={sm.removing || !!sm.selectedButton}
                    title="Select for delete"
                  />
                  {hasImage && (
                    <img
                      src={imageUrl}
                      alt={variant.displayName || variant.name}
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  )}
                  <button
                    className="btn-remove"
                    onClick={(e) => {
                      e.stopPropagation()
                      sm.handleRemoveVariant(selectedStage.code, variant.name)
                    }}
                    disabled={sm.removing}
                    title="Remove variant"
                  >
                    ×
                  </button>
                  {/* Button badge overlay */}
                  {variant.button && (
                    <div
                      className="button-badge-overlay"
                      onClick={(e) => {
                        e.stopPropagation()
                        sm.handleRemoveButton(variant)
                      }}
                      title={`Click to remove ${variant.button} button`}
                    >
                      <img src={backendMediaUrl(`/utility/buttons/${variant.button}.svg`)} alt={variant.button} />
                    </div>
                  )}
                </div>
                <div className="costume-info">
                  <h4>{variant.displayName || variant.name}</h4>
                </div>
              </div>
            )
          })}
          {dataReady && mexVariants.length === 0 && (
            <div className="no-costumes">
              <p>No variants in MEX yet</p>
            </div>
          )}
        </div>
        <PaginationBar pager={inIsoPager} />
      </div>

      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            Available to Import ({dataReady ? availableVariants.length : 'Loading...'})
            {sm.selectedVariants.size > 0 && ` - ${sm.selectedVariants.size} selected`}
          </h3>
          {availableVariants.length > 0 && (
            <div className="batch-controls">
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); sm.selectAllVariants(); }}
                disabled={sm.batchImporting}
              >
                Select All
              </button>
              {sm.selectedVariants.size > 0 && (
                <>
                  <button
                    className="btn-batch-import"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('start'); sm.handleBatchImportVariants(); }}
                    disabled={sm.batchImporting}
                  >
                    {sm.batchImporting
                      ? `Importing ${sm.batchProgress.current}/${sm.batchProgress.total}...`
                      : `Import All Selected (${sm.selectedVariants.size})`}
                  </button>
                  <button
                    className="btn-clear-selection"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); sm.clearVariantSelection(); }}
                    disabled={sm.batchImporting}
                  >
                    Clear
                  </button>
                </>
              )}
            </div>
          )}
        </div>
        {sm.transformFixNotice && (
          <div
            className={`transform-fix-notice ${sm.transformFixNotice.tone}`}
            role={sm.transformFixNotice.tone === 'warning' ? 'alert' : 'status'}
          >
            <div className="transform-fix-notice-copy">
              <strong>{sm.transformFixNotice.title}</strong>
              <span>{sm.transformFixNotice.message}</span>
            </div>
            <button
              type="button"
              className="transform-fix-notice-dismiss"
              onClick={() => sm.setTransformFixNotice(null)}
              aria-label="Dismiss Stadium transformation status"
            >
              ×
            </button>
          </div>
        )}
        <div className="costume-list" ref={sm.availableListRef}>
          {availableVariants.slice(availPager.start, availPager.end).map((variant, i) => {
            const idx = availPager.start + i
            const isVanilla = variant.filename?.startsWith('vanilla')
            const imageUrl = isVanilla
              ? selectedStage.vanillaImage
              : (variant.screenshotUrl ? `${BACKEND_URL}${variant.screenshotUrl}` : null)
            const hasImage = isVanilla ? true : variant.hasScreenshot
            const isSelected = sm.selectedVariants.has(variant.zipPath)

            return (
              <div
                key={idx}
                className={`costume-card ${isSelected ? 'selected' : ''} ${dataReady ? 'card-visible' : 'card-hidden'}`}
                style={{ animationDelay: dataReady ? `${Math.min(i * 30, 990)}ms` : '0ms' }}
                onMouseEnter={playHoverSound}
                onClick={() => { if (!sm.batchImporting) { playSound('boop'); sm.toggleVariantSelection(variant.zipPath); } }}
              >
                <div className="costume-preview">
                  {hasImage && (
                    <img
                      src={imageUrl}
                      alt={variant.name}
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  )}
                  <input
                    type="checkbox"
                    className="costume-checkbox"
                    checked={isSelected}
                    onChange={() => {}}
                    disabled={sm.batchImporting}
                  />
                  {variant.slippi_safe && (
                    <div className="slippi-badge slippi-badge-overlay" title="Slippi Safe">
                      ✓
                    </div>
                  )}
                  {variant.transformationSkins === 4 && (
                    <div
                      className="transform-skins-badge"
                      title="Includes custom textures for all four transformations"
                    >
                      4 FORMS
                    </div>
                  )}
                </div>
                <div className="costume-info">
                  <h4>{variant.name}</h4>
                </div>
              </div>
            )
          })}
          {dataReady && availableVariants.length === 0 && (
            <div className="no-costumes">
              <p>No variants available in storage for {selectedStage.name}</p>
            </div>
          )}
        </div>
        <PaginationBar pager={availPager} />
      </div>

      <StageMusicModal
        show={showStageMusic}
        stage={selectedStage.code}
        displayName={selectedStage.name}
        onClose={() => setShowStageMusic(false)}
      />
    </>
  )
}
