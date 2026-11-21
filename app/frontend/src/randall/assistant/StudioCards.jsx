// The model import in the chat: one card per call, drawn in the same tool-card
// language as the rest of the panel. The import's one job (import_model) is one
// card: where it is while it runs, then where it stopped or where it was saved,
// with the pictures of the costume. A studio stage call (in chats from before
// import_model) has a stage card: which stage ran and how it went, the pictures
// the stage made (thumbnails that open full size), what the call changed, what
// the studio flagged, and the next step it names. Routed by the reply's
// `studio_import` tag (see studio.js), so nothing here depends on the old import
// tools.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { backendMediaUrl } from '../../shared/config/config'
import { studioActivity } from './activity'
import {
  clip, freshEyesPictures, gamePictures, importJob, importStatusText, importTimeText, pictureCaption, pngFiles,
  stageRows, STAGE_STATUS, studioChanges, studioFighter, studioFixAt, studioNext, studioNotes, studioQuestions,
  studioStatusText,
} from './studio'
import { PICTURE_DRAG_TYPE } from './WorkbenchPanel'
import ImportToolsDownload from './ImportToolsDownload'
import { useDevDetails } from './devDetails'
import { useNow } from './clock'
import './WorkbenchPanel.css'
import './StudioCards.css'

const cx = (...names) => names.filter(Boolean).join(' ')
const fileUrl = id => backendMediaUrl(`/api/assistant/files/${id}?preview=1`)
// A picture dragged onto the message bar attaches its chat file record as it is
// (the workbench does the same); the local path stays behind.
const dragFile = file => event => {
  const { path: _path, ...record } = file
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData(PICTURE_DRAG_TYPE, JSON.stringify(record))
}

/** Full size over the whole window, like the workbench's pictures: Esc closes, arrows step. */
function PictureZoom({ items, index, onIndex, onClose }) {
  const item = items[index]
  useEffect(() => {
    const keys = event => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
      else if (event.key === 'ArrowLeft' && items.length > 1) { event.preventDefault(); onIndex((index - 1 + items.length) % items.length) }
      else if (event.key === 'ArrowRight' && items.length > 1) { event.preventDefault(); onIndex((index + 1) % items.length) }
    }
    window.addEventListener('keydown', keys, true)
    return () => window.removeEventListener('keydown', keys, true)
  }, [index, items.length])
  if (!item) return null
  const step = delta => event => { event.stopPropagation(); onIndex((index + delta + items.length) % items.length) }
  return createPortal(<div className="workbench-zoom" role="dialog" aria-modal="true" aria-label={item.caption}
    onClick={onClose}>
    <header className="workbench-zoom-bar" onClick={event => event.stopPropagation()}>
      <span className="workbench-zoom-name">{item.caption}</span>
      <span className="workbench-zoom-meta">{index + 1} of {items.length}</span>
      <button type="button" onClick={onClose} aria-label="Close" title="Close (Esc)">×</button>
    </header>
    {items.length > 1 && <button type="button" className="workbench-zoom-nav is-prev" aria-label="Previous picture"
      title="Previous (←)" onClick={step(-1)}>‹</button>}
    <img src={fileUrl(item.file.file_id)} alt={item.caption} onClick={event => event.stopPropagation()}
      draggable onDragStart={dragFile(item.file)} />
    {items.length > 1 && <button type="button" className="workbench-zoom-nav is-next" aria-label="Next picture"
      title="Next (→)" onClick={step(1)}>›</button>}
  </div>, document.body)
}

function Thumb({ item, onOpen }) {
  return <button type="button" className="assistant-studio-thumb" onClick={onOpen}
    title={`${item.caption} · open full size`} draggable onDragStart={dragFile(item.file)}>
    <img src={fileUrl(item.file.file_id)} alt={item.caption} loading="lazy" />
  </button>
}

/** A stage's pictures as thumbnails. `layout` "triptych" lays three across. */
export function StudioPictures({ files = [], caption = pictureCaption, layout = 'grid', label = 'Pictures' }) {
  const [open, setOpen] = useState(null)
  const items = files.map(file => ({ file, caption: caption(file) }))
  if (!items.length) return null
  return <>
    <ul className={cx('assistant-studio-pictures', `is-${layout}`, items.length <= 2 && 'is-few')} aria-label={label}>
      {items.map((item, index) => <li key={item.file.file_id}>
        <Thumb item={item} onOpen={() => setOpen(index)} />
        <span className="assistant-studio-caption">{item.caption}</span>
      </li>)}
    </ul>
    {open !== null && <PictureZoom items={items} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />}
  </>
}

/** In-game captures the reply carries as separate files: the costume beside the original. */
function GamePairs({ pairs }) {
  const [open, setOpen] = useState(null)
  const items = pairs.flatMap(pair => {
    const shot = pictureCaption(pair.import)
    return [{ file: pair.import, caption: `Your costume · ${shot}` }, { file: pair.vanilla, caption: `Original · ${shot}` }]
  })
  return <>
    <ul className="assistant-studio-pictures is-triptych" aria-label="In the game, beside the original">
      {pairs.map((pair, index) => <li key={pair.key} className="assistant-studio-pair">
        <div>
          <Thumb item={items[index * 2]} onOpen={() => setOpen(index * 2)} />
          <Thumb item={items[index * 2 + 1]} onOpen={() => setOpen(index * 2 + 1)} />
        </div>
        <span className="assistant-studio-caption">{pictureCaption(pair.import)} · yours, then the original</span>
      </li>)}
    </ul>
    {open !== null && <PictureZoom items={items} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />}
  </>
}

function Heading({ tool, activity, status, mark }) {
  const running = tool.status === 'running'
  // 'waiting' (an import that started nothing and waits on the user) is a '!' in the warning colour, never a ✓.
  const icon = mark || (running ? '◌' : activity.outcome === 'done' ? '✓' : activity.outcome === 'refused' ? '·' : '!')
  return <div className="assistant-tool-heading assistant-studio-heading">
    <span className={running ? 'assistant-working' : ''} aria-hidden="true">{icon}</span>
    <strong>{activity.phrase}</strong>
    {activity.stage && <em className="assistant-studio-stage">Stage {activity.stage} · {activity.title}</em>}
    <span className="assistant-studio-status">{status || studioStatusText(tool)}</span>
  </div>
}

function Shell({ tool, activity, className, status, mark, children }) {
  return <section className={cx('assistant-tool', 'assistant-studio', `is-${activity.outcome}`,
    activity.outcome === 'failed' && 'assistant-tool--error', className)}
    aria-label={activity.stage ? `Stage ${activity.stage}: ${activity.phrase}` : activity.phrase}>
    <Heading tool={tool} activity={activity} status={status} mark={mark} />
    {children}
  </section>
}

function Changes({ tool }) {
  const rows = studioChanges(tool)
  const reason = typeof tool.arguments?.reason === 'string' ? tool.arguments.reason.trim() : ''
  if (!rows.length && !reason) return null
  return <div className="assistant-studio-changes">
    {rows.map((row, index) => <p key={index} className="assistant-studio-change" title={row.full}>
      <span className="assistant-studio-key">{row.kind}</span>
      {row.op && <code>{row.op}</code>}
      {row.text && <span className="assistant-studio-value">{row.text}</span>}
    </p>)}
    {reason && <p className="assistant-studio-change assistant-studio-why" title={reason}>
      <span className="assistant-studio-key">Why</span><span>{clip(reason, 220)}</span></p>}
  </div>
}

function Problem({ result, activity }) {
  const error = typeof result.error === 'string' ? result.error.trim()
    : result.error ? String(result.error.message || result.error.detail || '') : ''
  const failed = typeof result.failed === 'string' ? result.failed.trim() : ''
  const text = failed || error
  if (!text) return null
  const fixAt = studioFixAt(result)
  const elsewhere = fixAt && Number(result.fix_at) !== activity.stage
  return <div className="assistant-studio-error" role="alert">
    <p>{text}</p>
    {elsewhere && <p className="assistant-studio-fix">The fix belongs at {fixAt}.</p>}
  </div>
}

function Flags({ result }) {
  const { warnings, notes } = studioNotes(result)
  const questions = studioQuestions(result)
  return <>
    {warnings.length > 0 && <ul className="assistant-studio-warnings">
      {warnings.map((text, index) => <li key={index}>{text}</li>)}
    </ul>}
    {questions.map(question => <p key={question.id} className="assistant-studio-question">
      <span className="assistant-studio-key">Open question</span>
      <span>{question.question}{question.proposal ? <em> Suggested: {question.proposal}</em> : null}</span>
    </p>)}
    {notes.length > 0 && <details className="assistant-studio-notes">
      <summary>{notes.length === 1 ? '1 note' : `${notes.length} notes`} from this step</summary>
      <ul>{notes.map((text, index) => <li key={index}>{text}</li>)}</ul>
    </details>}
  </>
}

function Next({ result }) {
  const next = studioNext(result)
  return next ? <p className="assistant-studio-next"><span className="assistant-studio-key">Next</span>{next}</p> : null
}

function StageCard({ tool, activity }) {
  const result = tool.result || {}
  return <Shell tool={tool} activity={activity}>
    <Changes tool={tool} />
    <Problem result={result} activity={activity} />
    <StudioPictures files={pngFiles(result)} label={`Pictures from ${activity.phrase.toLowerCase()}`} />
    <Flags result={result} />
    <Next result={result} />
  </Shell>
}

function gameFacts(result) {
  const report = result.report && typeof result.report === 'object' ? result.report : {}
  const facts = []
  const identity = report.identity || {}
  const loaded = identity.import || {}
  if (identity.fighter) facts.push(identity.fighter)
  if (Number.isInteger(loaded.loaded_slot)) facts.push(`costume slot ${loaded.loaded_slot}${loaded.slot_matches ? ', as asked' : ''}`)
  const frames = Array.isArray(report.frames) ? report.frames : []
  if (frames.length) {
    const caught = frames.filter(frame => frame?.status === 'captured' && frame?.import && frame?.vanilla).length
    facts.push(`${caught} of ${frames.length} moves caught beside the original`)
  }
  return facts
}

/** Stage 10: the costume in Dolphin beside the original, three across. */
function GameCard({ tool, activity }) {
  const result = tool.result || {}
  const { pairs, singles } = gamePictures(result)
  const facts = gameFacts(result)
  return <Shell tool={tool} activity={activity} className="assistant-studio-game">
    <Changes tool={tool} />
    <Problem result={result} activity={activity} />
    {facts.length > 0 && <p className="assistant-studio-facts">{facts.join(' · ')}</p>}
    {pairs.length > 0 && <GamePairs pairs={pairs} />}
    <StudioPictures files={singles} layout={singles.length >= 2 ? 'triptych' : 'grid'}
      label="In the game, beside the original" />
    {singles.length > 0 && <p className="assistant-studio-hint">Each picture is your costume on the left and the
      original on the right, the same moves on the same frame. Open one for full size.</p>}
    <Flags result={result} />
    <Next result={result} />
  </Shell>
}

/** test_in_game with finish_as: the costume saved to the vault. */
function FinishCard({ tool, activity }) {
  const result = tool.result || {}
  const vault = result.vault && typeof result.vault === 'object' ? result.vault : null
  return <Shell tool={tool} activity={activity}>
    <Changes tool={tool} />
    <Problem result={result} activity={activity} />
    {vault && <p className="assistant-studio-facts">{[vault.name ? `“${vault.name}”` : null, vault.character,
      result.installable === false ? 'saved, but it did not pass the install check' : 'in your vault'].filter(Boolean).join(' · ')}</p>}
    <StudioPictures files={pngFiles(result)} />
    <Flags result={result} />
  </Shell>
}

function FreshEyesCard({ tool, activity, context }) {
  const result = tool.result || {}
  const question = typeof tool.arguments?.question === 'string' ? tool.arguments.question.trim() : ''
  const shown = freshEyesPictures(tool, context)
  const problems = (Array.isArray(result.problems) ? result.problems : []).filter(Boolean)
  return <Shell tool={tool} activity={activity} className="assistant-studio-second">
    {question && <p className="assistant-studio-change" title={question}>
      <span className="assistant-studio-key">Asked</span><span className="assistant-studio-value">{clip(question, 260)}</span></p>}
    <StudioPictures files={shown.files} label="Pictures the second opinion saw" />
    {shown.missing > 0 && <p className="assistant-studio-hint">{shown.missing} more picture{shown.missing === 1 ? '' : 's'} it
      saw {shown.missing === 1 ? 'is' : 'are'} not in this chat.</p>}
    <Problem result={result} activity={activity} />
    {typeof result.answer === 'string' && result.answer.trim() && <blockquote className="assistant-studio-verdict">
      {result.answer.trim()}</blockquote>}
    {problems.length > 0 && <ul className="assistant-studio-problems" aria-label="What it saw wrong">
      {problems.map((problem, index) => <li key={index}>
        {typeof problem === 'object' ? <>{problem.where && <strong>{problem.where}</strong>}{problem.what || ''}</> : String(problem)}
      </li>)}
    </ul>}
    {!result.error && !result.failed && !result.unavailable && result.answer && !problems.length
      && <p className="assistant-studio-hint">It named no problems.</p>}
    <Flags result={result} />
  </Shell>
}

function DecideCard({ tool, activity }) {
  const result = tool.result || {}
  const from = Number(result.stale_from)
  return <Shell tool={tool} activity={activity}>
    <Changes tool={tool} />
    <Problem result={result} activity={activity} />
    {Number.isInteger(from) && <p className="assistant-studio-facts">Stage {from} and the stages after it run again with it.</p>}
    <Flags result={result} />
    <Next result={result} />
  </Shell>
}

/** Every stage at a glance: its status. */
function Stages({ rows }) {
  if (!rows.length) return null
  return <ol className="assistant-studio-stages" aria-label="Stages">
    {rows.map(row => <li key={row.stage} className={`is-${row.status}`} title={row.failure || undefined}>
      <span className="assistant-studio-stage-number">{row.stage}</span>
      <span>{row.title}</span>
      <small>{STAGE_STATUS[row.status] || row.status}{row.ops ? ` · ${row.ops} change${row.ops === 1 ? '' : 's'}` : ''}
        {row.outdated ? ' · built by older tools' : ''}</small>
    </li>)}
  </ol>
}

/** import_status: every stage at a glance. */
function StatusCard({ tool, activity }) {
  const result = tool.result || {}
  const rows = stageRows(result)
  const choices = Array.isArray(result.choices) ? result.choices.length : 0
  return <Shell tool={tool} activity={activity}>
    <Problem result={result} activity={activity} />
    <Stages rows={rows} />
    {choices > 0 && <p className="assistant-studio-facts">{choices} choice{choices === 1 ? '' : 's'} recorded</p>}
    <Flags result={result} />
    {typeof result.next === 'string' && <p className="assistant-studio-next"><span className="assistant-studio-key">Next</span>
      {result.next === 'finished' ? 'every stage is done' : result.next}</p>}
  </Shell>
}

/** Where a failed import stopped and the cause the reply gives (never one of the card's own). */
function importStopped(failed) {
  // rigswap's place in words ("while loading the model file"); an older chat's v4 reply gave a stage number
  const words = typeof failed.where === 'string' ? failed.where.trim() : ''
  const where = words ? `Stopped ${words}` : 'Stopped'
  const cause = typeof failed.cause === 'string' ? failed.cause.trim() : ''
  return cause ? `${where}: ${cause}` : `${where}.`
}

/** How long the import has taken, ticking every second while it runs: the status bar's clock (the turn's start, the
    same shared tick) in its words, "2 min 55 sec"; when it is over, that clock stopped at the end. */
function useImportTime(tool, context) {
  const now = useNow(tool.status === 'running')
  return importTimeText(tool, { startedAt: context?.turnStart?.get(tool.id), now })
}

/** import_model: the whole import as one card. Its AI cost only with developer details on: users never see dollars. */
function ImportCard({ tool, activity, context }) {
  const devDetails = useDevDetails()
  const result = tool.result || {}
  const job = importJob(result)
  const running = tool.status === 'running'
  const time = useImportTime(tool, context)
  const facts = [job.fighter, time && running ? `${time} so far` : time,
    devDetails && job.cost ? `${job.cost} for the import` : null].filter(Boolean)
  // The plain step while it runs; rigswap's raw last line (clock, file paths) only with developer details on.
  const last = job.step ? job.step.charAt(0).toUpperCase() + job.step.slice(1)
    : devDetails ? job.progress[job.progress.length - 1] : null
  return <Shell tool={tool} activity={activity} status={importStatusText(tool)} className="assistant-studio-import">
    <Problem result={result} activity={activity} />
    {job.failed && <p className="assistant-studio-facts">{importStopped(job.failed)}</p>}
    {facts.length > 0 && <p className="assistant-studio-facts">{facts.join(' · ')}</p>}
    {running && last && <p className="assistant-studio-hint" role="status">{last}</p>}
    <StudioPictures files={job.pictures} layout={job.pictures.length >= 3 ? 'triptych' : 'grid'}
      label="The costume file, at the game camera" />
    {job.saved && <p className="assistant-studio-saved">{[job.saved.name ? `Saved to your vault as “${job.saved.name}”` : 'Saved to your vault',
      job.saved.character, job.saved.installable === false ? 'it did not pass the install check' : null].filter(Boolean).join(' · ')}</p>}
    {job.notSaved && <p className="assistant-studio-hint">Not saved: {job.notSaved}</p>}
    {job.warning && <ul className="assistant-studio-warnings">
      <li>{job.warning.charAt(0).toUpperCase() + job.warning.slice(1)}</li>
    </ul>}
    {/* needs_tools: nothing ran; the same download as Settings > Model import tools, from here. */}
    {job.status === 'needs_tools' && !running && <ImportToolsDownload result={result} />}
    {job.saved?.notes?.length > 0 && <details className="assistant-studio-notes">
      <summary>{job.saved.notes.length === 1 ? '1 note' : `${job.saved.notes.length} notes`} from saving it</summary>
      <ul>{job.saved.notes.map((text, index) => <li key={index}>{String(text)}</li>)}</ul>
    </details>}
  </Shell>
}

/**
 * One studio call. `context` is `studioContext(messages)`: the fighter each
 * import is on and every picture of the chat (fresh_eyes names pictures by path).
 */
export default function StudioToolCard({ tool, context }) {
  const activity = studioActivity(tool, studioFighter(tool, context))
  const result = tool.result && typeof tool.result === 'object' ? tool.result : {}
  if (tool.name === 'import_model') return <ImportCard tool={tool} activity={activity} context={context} />
  if (tool.status === 'running') return <div className="assistant-mod-tool">
    <div className="assistant-download-activity assistant-studio-running" role="status">
      <span>{activity.phrase}</span>
      {activity.stage && <em className="assistant-studio-stage">Stage {activity.stage} · {activity.title}</em>}
      <span className="assistant-work-pulse" aria-hidden="true"><i /></span>
    </div>
  </div>
  if (tool.name === 'fresh_eyes') return <FreshEyesCard tool={tool} activity={activity} context={context} />
  if (tool.name === 'decide') return <DecideCard tool={tool} activity={activity} />
  if (Array.isArray(result.stages)) return <StatusCard tool={tool} activity={activity} />
  if (tool.name === 'test_in_game' && (tool.arguments?.finish_as || result.vault)) return <FinishCard tool={tool} activity={activity} />
  if (result.stage === 10 && !('mode' in result)) return <GameCard tool={tool} activity={activity} />
  return <StageCard tool={tool} activity={activity} />
}
