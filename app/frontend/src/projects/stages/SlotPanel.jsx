/**
 * SlotPanel - right-hand panel for a non-tournament stage picked in the
 * Stages list.
 *
 * Two columns, like the DAS VariantsPanel. Left: the stage's single slot
 * ("In ISO" -- vanilla, an installed vault skin, or something hand-edited)
 * with Restore Vanilla, plus any stages ADDED to the stage select from this
 * base. Right: the vault skins for this stage (the same variants the Vault's
 * stage page manages), each with two actions -- install into the slot
 * (replaces the original look) or add as a separate stage-select entry.
 */
import { useEffect } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import './StageSlots.css'

const STATE_LABELS = {
  vanilla: 'Vanilla',
  installed: null,
  modified: 'Modified stage file',
  unknown: 'Unrecognized stage file',
  missing: 'Stage file missing from project',
  'no-project': 'No project open',
}

export default function SlotPanel({ stage, ss, cs }) {
  useEffect(() => {
    ss.fetchSlot(stage.code)
  }, [stage.code]) // eslint-disable-line react-hooks/exhaustive-deps

  const detail = ss.slot?.stage?.code === stage.code ? ss.slot : null
  const slot = detail?.slot
  const available = detail?.available || []
  const added = detail?.added || []
  const ready = !!detail && !ss.slotLoading
  const busy = ss.busy || cs.batchInstallingStages || cs.removingCustomStages

  const installedSkin = slot?.state === 'installed' ? slot.installed : null
  const slotLabel = installedSkin ? installedSkin.name : (STATE_LABELS[slot?.state] || 'Loading...')
  const slotImage = installedSkin?.screenshotUrl
    ? backendMediaUrl(installedSkin.screenshotUrl)
    : backendMediaUrl(stage.artUrl)
  const canRestore = ready && slot && !['vanilla', 'no-project'].includes(slot.state)

  const skinImage = (skin) => skin.screenshotUrl
    ? backendMediaUrl(skin.screenshotUrl)
    : backendMediaUrl(stage.artUrl)

  const addAsNewStage = async (skin) => {
    if (busy) return
    const slug = await ss.wrapAsCustomStage(stage.code, skin)
    if (!slug) return
    await cs.handleInstallCustomStage(slug)
    await ss.fetchSlot(stage.code)
  }

  const removeAdded = async (name) => {
    if (busy) return
    await cs.handleRemoveCustomStage(name)
    await ss.fetchSlot(stage.code)
  }

  return (
    <>
      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            In ISO
            {stage.dualRoot && (
              <span className="slot-dual-note" title="This stage has an English and a Japanese file on the disc; both are written together">
                {' '}· both language files
              </span>
            )}
          </h3>
          <div className="iso-mod-actions">
            <button
              className="btn-extras-mode"
              onClick={() => { playSound('start'); ss.restoreVanilla(stage.code) }}
              onMouseEnter={playHoverSound}
              disabled={!canRestore || !!busy}
              title="Put the original stage from your vanilla ISO back"
            >
              {ss.busy === 'restore' ? 'Restoring...' : 'Restore Vanilla'}
            </button>
          </div>
        </div>
        <div className="costume-list existing slot-list">
          <div className={`costume-card existing-costume slot-card ${ready ? 'card-visible' : 'card-hidden'} slot-card--${slot?.state || 'loading'}`}>
            <div className="costume-preview">
              <img
                src={slotImage}
                alt={slotLabel}
                style={{ imageRendering: installedSkin?.screenshotUrl ? 'auto' : 'pixelated' }}
                onError={(e) => { e.target.style.display = 'none' }}
              />
              {slot?.state === 'installed' && (
                <div className="slot-card__tag slot-card__tag--installed">Installed skin</div>
              )}
              {slot?.state === 'vanilla' && (
                <div className="slot-card__tag">Original</div>
              )}
            </div>
            <div className="costume-info">
              <h4>{slotLabel}</h4>
            </div>
          </div>
        </div>

        {added.length > 0 && (
          <>
            <div className="costumes-section-header">
              <h3>Added as Separate Stages ({added.length})</h3>
            </div>
            <div className="costume-list existing slot-list">
              {added.map((entry, i) => (
                <div
                  key={entry.index}
                  className="costume-card existing-costume card-visible"
                  style={{ animationDelay: `${Math.min(i * 30, 990)}ms` }}
                >
                  <div className="costume-preview">
                    {entry.icon_url && (
                      <img
                        src={backendMediaUrl(entry.icon_url)}
                        alt={entry.name}
                        style={{ imageRendering: 'pixelated' }}
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                    )}
                    <button
                      className="btn-remove"
                      onClick={() => removeAdded(entry.name)}
                      disabled={!!busy}
                      title="Remove this added stage from the project"
                    >
                      ×
                    </button>
                  </div>
                  <div className="costume-info"><h4>{entry.name}</h4></div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>Available to Import ({ready ? available.length : 'Loading...'})</h3>
        </div>
        <div className="costume-list">
          {available.map((skin, i) => {
            const isCurrent = installedSkin?.id === skin.id
            const installing = ss.busy === `install:${skin.id}`
            const wrapping = ss.busy === `wrap:${skin.id}`
            return (
              <div
                key={skin.id}
                className={`costume-card slot-skin-card ${isCurrent ? 'selected' : ''} ${ready ? 'card-visible' : 'card-hidden'}`}
                style={{ animationDelay: ready ? `${Math.min(i * 30, 990)}ms` : '0ms' }}
                onMouseEnter={playHoverSound}
              >
                <div className="costume-preview">
                  <img
                    src={skinImage(skin)}
                    alt={skin.name}
                    style={{ imageRendering: skin.screenshotUrl ? 'auto' : 'pixelated' }}
                    onError={(e) => { e.target.style.display = 'none' }}
                  />
                  {isCurrent && (
                    <div className="slot-card__tag slot-card__tag--installed">In slot</div>
                  )}
                  {skin.slippi_safe && (
                    <div className="slippi-badge slippi-badge-overlay" title="Slippi Safe">✓</div>
                  )}
                </div>
                <div className="costume-info">
                  <h4>{skin.name}</h4>
                  <div className="slot-card-actions">
                    <button
                      className="btn-batch-import"
                      onMouseEnter={playHoverSound}
                      onClick={() => { playSound('start'); ss.installSkin(stage.code, skin) }}
                      disabled={!!busy || isCurrent}
                      title={`Replace ${stage.name} with this skin`}
                    >
                      {installing ? 'Installing...' : (isCurrent ? 'Installed' : 'Install')}
                    </button>
                    <button
                      className="btn-select-all"
                      onMouseEnter={playHoverSound}
                      onClick={() => { playSound('boop'); addAsNewStage(skin) }}
                      disabled={!!busy}
                      title="Keep the original and add this as its own stage-select entry"
                    >
                      {wrapping ? 'Adding...' : 'Add as new stage'}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
          {ready && available.length === 0 && (
            <div className="no-costumes">
              <p>No {stage.name} skins in the vault yet. Import a {stage.code}.dat mod to add one.</p>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
