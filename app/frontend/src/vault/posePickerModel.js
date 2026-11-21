/**
 * What the costume menu's pose picker lists, and which entry is the portrait
 * the costume shows now.
 *
 * `pose` is what a retake is asked for: null for the default pose (the
 * costume's original portrait), else a name from the character's library.
 * The default is "showing" only while no alternate is active: an uploaded
 * picture that is showing is no pose at all, so nothing is marked.
 */
export const DEFAULT_POSE_LABEL = 'Default pose'

export function showingPose(costume) {
  const activeId = costume?.active_csp_id
  if (!activeId) return null
  const active = (costume.alternateCsps || []).find(alt => alt.id === activeId)
  return active?.poseName || undefined
}

export function poseChoices(poses, costume) {
  const showing = showingPose(costume)
  return [
    // The pose menu files its own "Default pose" render under that label.
    { key: 'default', pose: null, label: DEFAULT_POSE_LABEL, thumbnailUrl: null,
      showing: showing === null || showing === DEFAULT_POSE_LABEL },
    ...poses.map(pose => ({
      key: `pose:${pose.name}`, pose: pose.name, label: pose.name,
      thumbnailUrl: pose.thumbnailUrl || null, showing: showing === pose.name,
    })),
  ]
}
