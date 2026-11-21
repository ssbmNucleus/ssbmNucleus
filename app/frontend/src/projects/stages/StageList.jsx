/**
 * StageList - left panel of StageMode: mode toggle buttons, the six DAS
 * stages with variant counts, the Custom Stages slot, then every other
 * versus stage (one replace slot each, from the backend stage catalog).
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import { DAS_STAGES } from './useStageVariants'
import { MusicIcon } from '../../shared/ui/Icons'
import './StageSlots.css'

function slotSummary(slotInfo) {
  if (!slotInfo) return { primary: '', available: 0 }
  const available = slotInfo.availableCount || 0
  switch (slotInfo.state) {
    case 'installed':
      return { primary: slotInfo.installed?.name || 'Skin installed', tone: 'installed', available }
    case 'modified':
    case 'unknown':
      return { primary: 'Modified', tone: 'modified', available }
    case 'missing':
      return { primary: 'File missing', tone: 'modified', available }
    case 'no-project':
      return { primary: '', available }
    default:
      return { primary: 'Vanilla', available }
  }
}

export default function StageList({ mode, onModeChange, onOpenMenuMusic, sm, cs, ss }) {
  const totalStages = DAS_STAGES.length + ss.moreStages.length
  return (
    <div className="fighters-list">
      <div className="fighters-header">
        <div className="mode-toggle">
          <button
            className={`mode-toggle-btn ${mode === 'characters' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'characters') { playSound('boop'); onModeChange('characters'); } }}
          >
            Fighters
          </button>
          <button
            className={`mode-toggle-btn ${mode === 'stages' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'stages') { playSound('boop'); onModeChange('stages'); } }}
          >
            Stages
          </button>
          <button
            className={`mode-toggle-btn ${mode === 'menus' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'menus') { playSound('boop'); onModeChange('menus'); } }}
          >
            Menus
          </button>
          <button
            className="mode-music-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onOpenMenuMusic(); }}
            title="Edit menu music"
            aria-label="Edit menu music"
          >
            <MusicIcon size={14} />
          </button>
        </div>
        <span className="fighters-count">{totalStages}</span>
      </div>
      <div className="fighter-items">
        {DAS_STAGES.map(stage => {
          const availableVariants = sm.getVariantsForStage(stage.code)
          const mexCount = sm.mexVariantCounts[stage.code] || 0
          return (
            <div
              key={stage.code}
              className={`fighter-item ${sm.selectedStage?.code === stage.code ? 'selected' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); sm.setSelectedStage(stage); }}
            >
              <img
                src={stage.vanillaImage}
                alt=""
                className="stage-list-icon"
                onError={(e) => e.target.style.display = 'none'}
              />
              <div className="fighter-content">
                <div className="fighter-name">{stage.name}</div>
                <div className="fighter-info">
                  <span className="costume-count">{mexCount} in MEX</span>
                  {availableVariants.length > 0 && (
                    <span className="available-count">{availableVariants.length} available</span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
        <div
          className={`fighter-item ${sm.selectedStage?.isCustom ? 'selected' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); sm.setSelectedStage({ code: 'custom', name: 'Custom Stages', isCustom: true }); }}
        >
          <div className="stage-list-icon stage-list-icon--placeholder">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
              <path d="M14 6l-3.75 5 2.85 3.8-1.6 1.2C9.81 13.75 7 10 7 10l-6 8h22L14 6z"/>
            </svg>
          </div>
          <div className="fighter-content">
            <div className="fighter-name">Custom Stages</div>
            <div className="fighter-info">
              <span className="costume-count">{cs.projectCustomStages.length} in ISO</span>
              {cs.vaultStages.length > 0 && (
                <span className="available-count">{cs.vaultStages.length} available</span>
              )}
            </div>
          </div>
        </div>
        {/* Every other versus stage: one replace slot each (see useStageSlots). */}
        {ss.moreStages.map(stage => {
          const summary = slotSummary(ss.slots[stage.code])
          return (
            <div
              key={stage.code}
              className={`fighter-item ${sm.selectedStage?.code === stage.code ? 'selected' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); sm.setSelectedStage({ ...stage, isSlot: true }); }}
              title={`${stage.name} (${stage.code})`}
            >
              <img
                src={backendMediaUrl(stage.artUrl)}
                alt=""
                className="stage-list-icon stage-list-icon--pixel"
                onError={(e) => e.target.style.display = 'none'}
              />
              <div className="fighter-content">
                <div className="fighter-name">{stage.name}</div>
                <div className="fighter-info">
                  {summary.primary && (
                    <span className={`costume-count ${summary.tone ? `slot-state--${summary.tone}` : ''}`}>
                      {summary.primary}
                    </span>
                  )}
                  {summary.available > 0 && (
                    <span className="available-count">{summary.available} available</span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
