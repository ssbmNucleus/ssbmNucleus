/**
 * PosePicker - the costume menu's list of poses to take the portrait with.
 *
 * "Default pose" and the character's saved poses (the library the Poses
 * button on the character's page makes). Picking one renders a preview on the
 * portrait; nothing is replaced until the user keeps it, and a kept pose is
 * the portrait the costume shows from then on. "New pose with this model"
 * opens the pose maker on the costume's own model: a pose made on the vanilla
 * model can sit badly on a model of another shape.
 */
import { useEffect, useState } from 'react'
import { api } from '../shared/transport/api'
import { backendMediaUrl } from '../shared/config/config.js'
import { playSound } from '../shared/audio/sounds'
import { poseChoices } from './posePickerModel.js'

export default function PosePicker({ character, costume, onPick, onNew, onClose }) {
  const [poses, setPoses] = useState(null) // null while the list loads
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    setPoses(null)
    setError(null)
    api.get(`/storage/poses/list/${character}`)
      .then(data => { if (live) setPoses(data.poses || []) })
      .catch(err => { if (live) { setPoses([]); setError(err.message) } })
    return () => { live = false }
  }, [character])

  const choices = poseChoices(poses || [], costume)

  return (
    <div className="edit-modal-pose-picker" role="dialog" aria-label="Take the portrait with a pose">
      <div className="edit-modal-pose-picker-head">
        <span>Take the portrait with</span>
        <button className="edit-modal-pose-picker-close" onClick={() => { playSound('back'); onClose() }}
          aria-label="Close" title="Close">✕</button>
      </div>
      <div className="edit-modal-pose-picker-list">
        {choices.map(choice => (
          <button key={choice.key} className="edit-modal-pose-choice"
            onClick={() => { playSound('boop'); onPick(choice.pose) }}
            title={choice.showing
              ? 'Take this pose again (you confirm before it replaces anything)'
              : 'Preview the portrait in this pose (you confirm before it replaces anything)'}>
            <span className="edit-modal-pose-thumb">
              {choice.thumbnailUrl
                ? <img src={backendMediaUrl(choice.thumbnailUrl)} alt=""
                    onError={(e) => { e.target.style.display = 'none' }} />
                : <span>{choice.label[0].toUpperCase()}</span>}
            </span>
            <span className="edit-modal-pose-name">{choice.label}</span>
            {choice.showing && <span className="edit-modal-pose-showing">showing</span>}
          </button>
        ))}
      </div>
      {poses === null && <div className="edit-modal-pose-picker-note">Loading poses…</div>}
      {error && <div className="edit-modal-pose-picker-note">Could not list the saved poses: {error}</div>}
      {poses !== null && !error && poses.length === 0 && !onNew && (
        <div className="edit-modal-pose-picker-note">
          No saved poses for this character yet. Make one with Poses on the character's page.
        </div>
      )}
      {/* The pose maker, already showing this costume's model instead of the vanilla one */}
      {onNew && (
        <button className="edit-modal-pose-choice edit-modal-pose-new"
          onClick={() => { playSound('start'); onNew() }}
          title="Open the pose maker with this costume's own model loaded, to pose it and save a new pose">
          <span className="edit-modal-pose-thumb"><span>+</span></span>
          <span className="edit-modal-pose-name">New pose with this model…</span>
        </button>
      )}
    </div>
  )
}
