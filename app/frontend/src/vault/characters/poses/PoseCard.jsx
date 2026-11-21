import { useState } from 'react'
import { TrashIcon } from '../../../shared/ui/Icons'
import { appConfirm } from '../../../shared/ui/appDialogs'
import { backendMediaUrl } from '../../../shared/config/config.js'
import { api } from '../../../shared/transport/api'

// Pose Card Component
export default function PoseCard({
  pose,
  character,
  onDelete,
  onClick,
  onStartFrom,
  defaultPoseName = '',
  onSetDefaultPose,
  settingDefaultPose = false,
}) {
  const [deleting, setDeleting] = useState(false)
  const isDefaultPose = defaultPoseName && pose.name === defaultPoseName

  const handleDelete = async (e) => {
    e.stopPropagation()
    if (!await appConfirm(`Delete pose "${pose.name}"?`, {
      title: 'Delete Pose',
      confirmText: 'Delete',
    })) return

    setDeleting(true)
    try {
      await api.post('/storage/poses/delete', { character, poseName: pose.name })
      onDelete(pose.name)
    } catch (err) {
      console.error('[PoseCard] Delete error:', err)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className={`pm-pose-card${isDefaultPose ? ' is-default' : ''}`} onClick={onClick} style={{ cursor: 'pointer' }}>
      <div className="pm-pose-image">
        {pose.hasThumbnail ? (
          <img
            src={backendMediaUrl(pose.thumbnailUrl)}
            alt={pose.name}
            onError={(e) => { e.target.style.display = 'none' }}
          />
        ) : (
          <div className="pm-pose-placeholder">
            {pose.name.charAt(0).toUpperCase()}
          </div>
        )}
        {onStartFrom && (
          <button
            className="pm-pose-edit"
            onClick={(e) => { e.stopPropagation(); onStartFrom(pose) }}
            title="Create a new pose starting from this one"
          >
            ✎
          </button>
        )}
        {isDefaultPose && (
          <span className="pm-pose-default">Default</span>
        )}
        {onSetDefaultPose && !isDefaultPose && (
          <button
            className="pm-pose-set-default"
            onClick={(e) => { e.stopPropagation(); onSetDefaultPose(pose) }}
            disabled={settingDefaultPose}
            title="Use this for new and missing custom character CSPs"
          >
            Make Default
          </button>
        )}
        <button
          className="pm-pose-delete"
          onClick={handleDelete}
          disabled={deleting}
          title="Delete pose"
        >
          <TrashIcon />
        </button>
      </div>
      <div className="pm-pose-name">{pose.name}</div>
    </div>
  )
}
