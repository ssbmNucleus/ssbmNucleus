import { ChatInput } from '../chat/ChatUI'
import { Randall } from '../../shared/ui/Sprites'
import { StartChips, TaskPill } from './TaskPicker'
import { StartPickControl } from './StartPicker'

/**
 * Randall's message bar, laid out like the Claude app's composer: one box, the
 * textarea on top and a control row inside it (attach, the task pill, the
 * starting pick; send at the right).
 *
 * `start` is an empty chat (the new-chat screen): the bar sits in the middle of
 * the page instead of at the bottom (AssistantPanel.css `.coach-inputarea.is-start`),
 * with Randall and one line above the box and the starting points as chips under
 * it. Both are out of the bar's flow, so choosing a workflow (the chips fade out,
 * the pill and the pick control appear in the control row) never moves the box.
 * The first message turns the chat into a transcript and the bar glides to the
 * bottom.
 *
 * tasks        every starting point (status.tasks), the not-built ones included
 * ready        status has answered (until then nothing under the box: no flash of the old starters)
 * starters     [[label, prompt]] offered instead when the backend serves no tasks
 * task/locked  the chat's task, and whether the chat already has messages
 * picker/pick  the task's starting pick (startPick.pickerFor) and what was picked
 * pickSources  {metadata, fighters, stages} for the picker
 * attach       the + button; children: the rows above the box (notices, attachments)
 * input        ChatInput's props
 * ...footer    the footer element's own props (the drag-and-drop handlers)
 */
export default function Composer({ start, tasks, ready, starters = [], task, locked, picker, pick, pickSources = {},
  busy, pillDisabled, pickDisabled, onTask, onPick, onClearPick, onStarter, onSubmit, attach, nowrapPlaceholder,
  input, children, ...footer }) {
  return <footer {...footer} className={`coach-inputarea${start ? ' is-start' : ''}`}>
    {start && <div className="randall-start-greeting">
      <span className="randall-start-sprite"><Randall size={56} className="coach-empty-randall" /></span>
      <p>What are we making today?</p>
    </div>}
    {children}
    <form className={nowrapPlaceholder ? 'randall-task-composer' : undefined} onSubmit={event => { event.preventDefault(); onSubmit() }}>
      <ChatInput {...input} controls={<>
        {attach}
        {(task || locked) && <TaskPill tasks={tasks} value={task} locked={locked} disabled={pillDisabled} onChange={onTask} />}
        <StartPickControl picker={picker} pick={pick} disabled={pickDisabled} {...pickSources} onPick={onPick} onClear={onClearPick} />
      </>} />
    </form>
    {start && ready && (tasks.length > 0
      ? <StartChips tasks={tasks} away={Boolean(task)} disabled={busy} onPick={onTask} />
      : starters.length > 0 && <div className="randall-start-points">
        <div className="randall-start-group"><div className="randall-start-row">
          {starters.map(([label, prompt]) => <button key={label} type="button" className="randall-start-point" disabled={busy}
            onClick={() => onStarter(prompt)}><span>{label}</span></button>)}
        </div></div>
      </div>)}
  </footer>
}
