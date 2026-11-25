/**
 * AddingCard - a game on its way onto the shelf (the running shelf_add job, play/adding.py),
 * shown at the end of the grid until the job ends and the shelf reloads. A replace (a new
 * version of a game already there) says Replacing.
 */
import { jobPercent } from '../shared/jobs/jobOutcome'
import { addingCard } from './playCards'

export default function AddingCard({ job }) {
  if (!job) return null
  const percent = jobPercent(job)
  const { name, badge, detail } = addingCard(job)
  return (
    <article className="play-card play-card--adding" aria-busy="true">
      <div className="play-cover play-cover--plain">
        <span className="play-cover-title" aria-hidden="true">{name}</span>
        <span className="play-cover-badge">{badge}</span>
      </div>
      <div className="play-card-body">
        <h3 className="play-card-name" title={name}>{name}</h3>
        <p className="play-card-reason play-card-reason--launching">{detail}</p>
        <div className="play-progress" role="progressbar" aria-label={`${badge} ${name}`}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
          <div className="play-progress-fill" style={{ width: `${percent ?? 0}%` }} />
        </div>
      </div>
      <div className="play-card-actions">
        <span className="play-card-percent">{percent != null ? `${percent}%` : ''}</span>
      </div>
    </article>
  )
}
