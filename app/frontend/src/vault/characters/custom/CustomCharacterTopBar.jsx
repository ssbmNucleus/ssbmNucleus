import { playSound, playHoverSound } from '../../../shared/audio/sounds'
import { backendMediaUrl } from '../../../shared/config/config.js'

// Top bar of a custom character's page: back, the default-pose menu, poses,
// sounds, and the in-game test button.
export default function CustomCharacterTopBar({
  detail, onBack, setShowPoseManager, character, defaultPoseMenuRef,
  showDefaultPoseMenu, applyingDefaultPose, poseList, setShowDefaultPoseMenu, defaultPoseButtonLabel,
  handleSetDefaultPose, testActive, inGameTest,
}) {
  return (
    <div className="detail-top-bar">
      <button
        onClick={() => { playSound('back'); onBack(); }}
        className="back-button"
      >
        ← Back to Custom Characters
      </button>
      <div className="detail-top-actions">
        <button
          className="manage-poses-cta"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); setShowPoseManager(true) }}
          title="Manage CSP / portrait poses for this character's costumes"
        >
          🎭 Manage Poses
        </button>
        <div className="default-pose-picker" ref={defaultPoseMenuRef}>
          <button
            type="button"
            className={`default-pose-menu-btn${showDefaultPoseMenu ? ' active' : ''}${applyingDefaultPose ? ' is-applying' : ''}`}
            disabled={applyingDefaultPose || poseList.length === 0}
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); setShowDefaultPoseMenu(open => !open) }}
            aria-haspopup="menu"
            aria-expanded={showDefaultPoseMenu}
            title={poseList.length === 0
              ? 'Create a pose in Manage Poses first, then pick it here for new and missing CSPs'
              : 'Use this pose for new and missing custom character CSPs'}
          >
            {defaultPoseButtonLabel}
          </button>
          {showDefaultPoseMenu && (
            <div className="default-pose-popover" role="menu" aria-label="Default pose">
              <div className="default-pose-popover-title">Default Pose</div>
              <div className="default-pose-grid">
                {poseList.map(pose => (
                  <button
                    key={pose.name}
                    type="button"
                    className={`default-pose-card${pose.name === detail?.default_pose ? ' active' : ''}`}
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); handleSetDefaultPose(pose.name) }}
                    disabled={applyingDefaultPose}
                    role="menuitem"
                    title={`Use ${pose.name} for new and missing CSPs`}
                  >
                    <div className="default-pose-card-image">
                      {pose.hasThumbnail ? (
                        <img
                          src={backendMediaUrl(pose.thumbnailUrl)}
                          alt={pose.name}
                          draggable={false}
                        />
                      ) : (
                        <span>{pose.name.charAt(0).toUpperCase()}</span>
                      )}
                    </div>
                    <span className="default-pose-card-name">{pose.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        {!testActive && (
          <button
            className="ingame-test-cta"
            onMouseEnter={playHoverSound}
            onClick={() => {
              playSound('start')
              inGameTest.startCustomCharacterTest({ slug: character.slug, name: character.name })
            }}
            title="Build a one-mod test ISO and play a short match to verify it loads"
          >
            🎮 Test in Game
          </button>
        )}
      </div>
    </div>
  )
}
