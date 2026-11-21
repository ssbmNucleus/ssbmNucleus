import HexagonLoader from '../../shared/ui/HexagonLoader'
import ViewerAnimPopover from './ViewerAnimPopover'

// The right-hand 3D preview: the live viewer surface with its stage animation
// controls, Randall's checkpoint offer, the animation popover, and the
// loading / reconnect placeholders.
export default function PreviewPanel({
  panelSizes, isStage, stageAnimation, paintMembers, refreshTextures,
  viewerWs, connectionFailed, skinCreatorCanvasRef, viewerStreaming, streamCanvasRef,
  capabilityWarning, pendingCheckpoint, adoptCheckpoint, setAdoptedRevision, setPendingCheckpoint,
  animList, skinCreatorLoading, selectedAnim, handleReconnect, skinCreatorReconnecting,
  skinCreatorReconnectAttempts, skinCreatorMaxReconnectAttempts,
}) {
  return (
    <div className="skin-creator-right-panel" style={{ width: panelSizes.rightPanelWidth }}>
      {/* 3D Preview */}
      <div className="skin-creator-3d-container">
        <div className="skin-creator-panel-header">
          {isStage && <div className="stage-animation-controls">
            <button type="button" onClick={() => window.electron.viewerSend({ type: stageAnimation.playing ? 'animPause' : 'animPlay' })}>{stageAnimation.playing ? 'Pause' : 'Play'}</button>
            <input aria-label="Stage animation frame" type="range" min="0" max={Math.max(1, (stageAnimation.frameCount || stageAnimation.totalFrames || 1) - 1)} value={stageAnimation.frame || 0} onChange={event => window.electron.viewerSend({ type: 'animSetFrame', frame: Number(event.target.value) })} />
          </div>}
          <span>3D Preview{paintMembers.length ? ' · Popo + Nana' : ''}</span>
          <button
            className="refresh-btn"
            onClick={refreshTextures}
            title="Reset the view and refresh textures"
            disabled={!viewerWs || connectionFailed}
          >
            ↻
          </button>
        </div>
        <div
          ref={skinCreatorCanvasRef}
          className="skin-creator-3d viewer-canvas-surface"
          tabIndex={0}
          aria-label="3D costume preview. Drag to rotate, right-drag to pan, scroll to zoom."
        >
          {viewerStreaming && <canvas ref={streamCanvasRef} className="viewer-stream-canvas" />}
          {capabilityWarning && <div className="viewer-capability-warning" role="status">{capabilityWarning}</div>}
          {pendingCheckpoint && (
            <div className="viewer-capability-warning" role="status">
              Randall edited this skin in chat.
              <button type="button" className="chat-unlock" onClick={() => adoptCheckpoint(pendingCheckpoint)}>
                Load it
              </button>
              <button type="button" className="chat-unlock" onClick={() => {
                setAdoptedRevision(pendingCheckpoint.revision || 0); setPendingCheckpoint(null)
              }}>Keep mine</button>
            </div>
          )}
          {!isStage && !paintMembers.length && animList.length > 0 && !connectionFailed && !skinCreatorLoading && (
            <ViewerAnimPopover
              animations={animList}
              selectedAnim={selectedAnim}
              state={stageAnimation}
              onLoad={symbol => window.electron.viewerSend({ type: 'loadAnim', symbol })}
              onToggle={() => window.electron.viewerSend({ type: stageAnimation.playing ? 'animPause' : 'animPlay' })}
              onSetFrame={frame => window.electron.viewerSend({ type: 'animSetFrame', frame })}
            />
          )}
          {connectionFailed ? (
            <div className="viewer-placeholder connection-failed">
              <span>Connection Lost</span>
              <button className="reconnect-btn" onClick={handleReconnect}>
                Reconnect
              </button>
            </div>
          ) : skinCreatorLoading ? (
            <div className="viewer-placeholder">
              <HexagonLoader size={56} decorative />
              <span>Loading…</span>
            </div>
          ) : skinCreatorReconnecting ? (
            <div className="viewer-placeholder reconnecting">
              <HexagonLoader size={56} decorative />
              <span>Reconnecting…</span>
              <p>Attempt {skinCreatorReconnectAttempts}/{skinCreatorMaxReconnectAttempts}</p>
            </div>
          ) : (
            <div className="viewer-hint">
              Drag to rotate | Scroll to zoom | Right-drag to pan
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
