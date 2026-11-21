// The character's built-in pose, shown in the pose library like any saved
// pose. It has no pose file: the thumbnail is the base costume's portrait and
// batch renders go through the DEFAULT_POSE_NAME sentinel (poses.py).
export const DEFAULT_POSE_NAME = '__default__'
export const DEFAULT_POSE_LABEL = 'Default pose'

export default function BasePoseCard({ thumbnailUrl, label, title, isDefault = false, onClick }) {
  return (
    <div
      className={`pm-pose-card pm-base-card${isDefault ? ' is-default' : ''}`}
      onClick={onClick}
      title={title}
      style={{ cursor: 'pointer' }}
    >
      <div className="pm-pose-image">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={label}
            draggable={false}
            onError={(e) => { e.target.style.display = 'none' }}
          />
        ) : (
          <div className="pm-pose-placeholder">{label.charAt(0).toUpperCase()}</div>
        )}
        <span className="pm-pose-builtin">Built in</span>
        {isDefault && <span className="pm-pose-default">Default</span>}
      </div>
      <div className="pm-pose-name">{label}</div>
    </div>
  )
}
