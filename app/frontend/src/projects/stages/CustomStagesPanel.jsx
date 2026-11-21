/**
 * CustomStagesPanel - custom stages view of StageMode: stages installed
 * in the ISO and vault stages available to import (with batch controls).
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import PaginationBar from '../../shared/ui/PaginationBar'
import usePagination from '../../shared/hooks/usePagination'

export default function CustomStagesPanel({ cs }) {
  const inIsoPager = usePagination(cs.projectCustomStages.length, 'custom-iso')
  const vaultPager = usePagination(cs.vaultStages.length, 'custom-vault')
  return (
    <>
      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            In ISO ({cs.projectCustomStages.length})
            {cs.selectedInstalledCustomStages.size > 0 && ` - ${cs.selectedInstalledCustomStages.size} selected`}
          </h3>
          {cs.projectCustomStages.length > 0 && (
            <div className="iso-mod-actions">
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); cs.selectAllInstalledCustomStages(); }}
                disabled={cs.removingCustomStages}
              >
                Select All
              </button>
              {cs.selectedInstalledCustomStages.size > 0 && (
                <>
                  <button
                    className="btn-batch-import btn-batch-delete"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('start'); cs.handleBatchRemoveCustomStages(); }}
                    disabled={cs.removingCustomStages}
                  >
                    Delete Selected ({cs.selectedInstalledCustomStages.size})
                  </button>
                  <button
                    className="btn-clear-selection"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); cs.clearInstalledCustomStageSelection(); }}
                    disabled={cs.removingCustomStages}
                  >
                    Clear
                  </button>
                </>
              )}
            </div>
          )}
        </div>
        <div className="costume-list existing">
          {cs.projectCustomStages.slice(inIsoPager.start, inIsoPager.end).map((stage, i) => {
            const isSelected = cs.selectedInstalledCustomStages.has(stage.name)
            return (
            <div key={stage.index} className={`costume-card existing-costume card-visible ${isSelected ? 'selected' : ''}`} style={{ animationDelay: `${Math.min(i * 30, 990)}ms` }}>
              <div className="costume-preview">
                {stage.icon_url && (
                  <img src={backendMediaUrl(stage.icon_url)} alt={stage.name} style={{ imageRendering: 'pixelated' }} onError={e => e.target.style.display = 'none'} />
                )}
                <input
                  type="checkbox"
                  className="costume-checkbox"
                  checked={isSelected}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => { playSound('boop'); cs.toggleInstalledCustomStageSelection(stage.name); }}
                  disabled={cs.removingCustomStages}
                  title="Select for delete"
                />
                <button className="btn-remove" onClick={() => cs.handleRemoveCustomStage(stage.name)} title="Remove stage">×</button>
              </div>
              <div className="costume-info"><h4>{stage.name}</h4></div>
            </div>
            )
          })}
          {cs.projectCustomStages.length === 0 && (
            <div className="no-costumes"><p>No custom stages installed</p></div>
          )}
        </div>
        <PaginationBar pager={inIsoPager} />
      </div>
      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            Available to Import ({cs.vaultStages.length})
            {cs.selectedCustomStages.size > 0 && ` - ${cs.selectedCustomStages.size} selected`}
          </h3>
          {cs.vaultStages.length > 0 && (
            <div className="batch-controls">
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); cs.selectAllCustomStages(); }}
                disabled={cs.batchInstallingStages}
              >
                Select All
              </button>
              {cs.selectedCustomStages.size > 0 && (
                <>
                  <button
                    className="btn-batch-import"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('start'); cs.handleBatchInstallStages(); }}
                    disabled={cs.batchInstallingStages}
                  >
                    {cs.batchInstallingStages
                      ? (cs.batchStageProgress.message
                          || `Installing ${cs.batchStageProgress.current}/${cs.batchStageProgress.total}...`)
                      : `Install All Selected (${cs.selectedCustomStages.size})`}
                  </button>
                  <button
                    className="btn-clear-selection"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); cs.clearCustomStageSelection(); }}
                    disabled={cs.batchInstallingStages}
                  >
                    Clear
                  </button>
                </>
              )}
            </div>
          )}
        </div>
        <div className="costume-list">
          {cs.vaultStages.slice(vaultPager.start, vaultPager.end).map((stage, i) => {
            const isSelected = cs.selectedCustomStages.has(stage.slug)
            return (
              <div
                key={stage.slug}
                className={`costume-card card-visible ${isSelected ? 'selected' : ''}`}
                style={{ animationDelay: `${Math.min(i * 30, 990)}ms` }}
                onMouseEnter={playHoverSound}
                onClick={() => { if (!cs.batchInstallingStages) { playSound('boop'); cs.toggleCustomStageSelection(stage.slug); } }}
              >
                <div className="costume-preview">
                  {stage.has_icon && (
                    <img src={backendMediaUrl(stage.icon_url)} alt={stage.name} style={{ imageRendering: 'pixelated' }} onError={e => e.target.style.display = 'none'} />
                  )}
                  <input
                    type="checkbox"
                    className="costume-checkbox"
                    checked={isSelected}
                    onChange={() => {}}
                    disabled={cs.batchInstallingStages}
                  />
                </div>
                <div className="costume-info">
                  <h4>{stage.name}</h4>
                </div>
              </div>
            )
          })}
          {cs.vaultStages.length === 0 && (
            <div className="no-costumes"><p>No custom stages in vault</p></div>
          )}
        </div>
        <PaginationBar pager={vaultPager} />
      </div>
    </>
  )
}
