import { useEffect, useId, useRef, useState } from 'react'
import { isStartable, labelFor } from './taskModes'

const ASK = { id: null, label: 'Ask', hint: 'Chat about anything' }

/** The tasks under their headings, in first-seen order; a row with no `group` joins the previous one. */
export function groupTasks(tasks) {
  const groups = []
  for (const task of tasks) {
    const name = typeof task.group === 'string' && task.group ? task.group : groups[groups.length - 1]?.name || ''
    const group = groups.find(entry => entry.name === name) || groups[groups.push({ name, tasks: [] }) - 1]
    group.tasks.push(task)
  }
  return groups
}

const Check = () => <svg className="randall-task-check" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 6 9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>

// The composer's task pill, in the box's control row (where the Claude app has its
// mode selector). Free to change on an empty chat: its menu lists Ask (a plain
// chat), then every starting point under its group, the ones Randall cannot run
// disabled and marked "Use MCP" (reachable with the arrows, as a menu's
// disabled items are, but nothing happens on them). Once the chat has a message
// the task is fixed (one chat holds one task), so the pill only names it.
// `tasks` is every starting point (status.tasks); only a startable one can be
// the pill's value. Picking moves focus wherever `onChange` sends it.
export function TaskPill({ tasks, value, locked, disabled, onChange }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null), pill = useRef(null)
  const menuId = useId()
  const startable = tasks.filter(isStartable)
  const label = labelFor(startable, value)
  const current = label ? startable.find(task => task.id === value) : null
  useEffect(() => { if (locked || disabled) setOpen(false) }, [locked, disabled])
  useEffect(() => {
    if (!open) return
    wrap.current?.querySelector('[role="menuitemradio"][aria-checked="true"]')?.focus()
    const outside = event => { if (!wrap.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  // No tasks in this build, or a locked chat whose task this build does not offer
  // (a retired id, a stub): say nothing rather than call it "Ask".
  if (!startable.length || (locked && value && !label)) return null
  const close = () => { setOpen(false); pill.current?.focus() }
  const menuKeys = event => {
    const items = [...event.currentTarget.querySelectorAll('[role="menuitemradio"]')]
    const at = items.indexOf(document.activeElement)
    const move = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key]
    if (move !== undefined) { event.preventDefault(); items[(move + items.length) % items.length]?.focus() }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
    // Focus the pill first so the browser's own Tab carries on from there.
    else if (event.key === 'Tab') close()
  }
  const option = task => {
    const ready = !task.id || isStartable(task)
    return <button key={task.id || 'ask'} type="button" role="menuitemradio" tabIndex={-1}
      className={`randall-task-option${ready ? '' : ' is-unavailable'}`}
      aria-checked={(task.id || null) === (label ? value : null)} aria-disabled={ready ? undefined : true}
      title={task.hint || undefined} onClick={ready ? () => { setOpen(false); onChange(task.id || null) } : undefined}>
      {task.id ? <TaskIcon task={task} size={15} /> : <AskIcon />}
      <span className="randall-task-option-label">{task.label}</span>
      {ready ? <Check /> : <span className="randall-task-soon">Use MCP</span>}
    </button>
  }
  return <div className="randall-task-picker" ref={wrap}>
    <button ref={pill} type="button" className={`randall-task-pill${current ? ' is-task' : ''}${locked ? ' is-locked' : ''}`}
      disabled={disabled && !locked} aria-disabled={locked || undefined}
      aria-haspopup={locked ? undefined : 'menu'} aria-expanded={locked ? undefined : open} aria-controls={open ? menuId : undefined}
      aria-label={locked ? `Chat task: ${label || 'Ask'}` : `Chat task: ${label || 'Ask'}. Change task`}
      title={locked ? 'This chat keeps its task. Start a new chat for something else.' : 'Change what this chat is for'}
      onClick={() => { if (!locked) setOpen(was => !was) }}
      onKeyDown={event => { if (!locked && !open && ['ArrowUp', 'ArrowDown'].includes(event.key)) { event.preventDefault(); setOpen(true) } }}>
      {current && <TaskIcon task={current} size={14} />}
      <span className="randall-task-pill-label">{label || 'Ask'}</span>
      {!locked && <svg className="randall-task-pill-caret" width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"><path d="m2.5 6.25 2.5-2.5 2.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
    </button>
    {open && <div className="randall-task-menu" id={menuId} role="menu" aria-label="Chat task" onKeyDown={menuKeys}>
      {option(ASK)}
      {groupTasks(tasks).map((group, index) => group.name
        ? <div key={group.name} className="randall-task-menu-group" role="group" aria-label={group.name}>
          <span className="randall-task-menu-label" aria-hidden="true">{group.name}</span>
          {group.tasks.map(option)}
        </div>
        : <div key={`flat-${index}`} className="randall-task-menu-group">{group.tasks.map(option)}</div>)}
    </div>}
  </div>
}

const AskIcon = () => <svg className="randall-task-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z" /></svg>

// A task's small outline icon, chosen by what it starts from (its `picker`): a
// brush for a costume, a cube for a model on a fighter, a paint drop over a stage
// platform for a stage. A starting point with no picker (a stub) gets the
// generic spark. The sidebar rows, the pill, its menu and the chips use it.
export function TaskIcon({ task, size = 18 }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, className: 'randall-task-icon' }
  if (task?.picker === 'costume') return <svg {...common}><path d="M18.4 2.6a2 2 0 0 1 2.9 2.9L12 14.8 9.2 12z" /><path d="M9 12.2c-2.2 0-4 1.8-4 4 0 1.6-.9 2.7-2.5 3.3 1.2.9 2.7 1.4 4.4 1.4 3 0 5.2-2.3 5.2-5.1z" /></svg>
  if (task?.picker === 'fighter') return <svg {...common}><path d="m12 2.8 8 4.6v9.2l-8 4.6-8-4.6V7.4z" /><path d="m4 7.4 8 4.6 8-4.6M12 12v9.2" /></svg>
  if (task?.picker === 'stage') return <svg {...common}><path d="M12 2.8s-3.6 4.1-3.6 6.6a3.6 3.6 0 0 0 7.2 0c0-2.5-3.6-6.6-3.6-6.6z" /><path d="M3 16h18M6 16l1.6 4.2h8.8L18 16" /></svg>
  return <svg {...common}><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1" /></svg>
}

// The empty chat's starting points: one compact row of chips per `group` under the
// centred composer (Characters, then Stages), each with its icon, in the backend's
// order. A starting point Randall cannot run (`available: false`) is a plain
// chip marked "Use MCP": not a button, so nothing to press or tab to, and a
// screen reader reads it with the rest. `away` (a workflow is chosen; the pill in
// the composer names it now) fades the row out and makes it inert, without
// unmounting it, so nothing under the composer reflows.
export function StartChips({ tasks, onPick, disabled, away = false }) {
  const chip = task => isStartable(task)
    ? <button key={task.id} type="button" className="randall-start-point" disabled={disabled} title={task.hint || undefined}
      onClick={() => onPick(task.id)}><TaskIcon task={task} size={15} /><span>{task.label}</span></button>
    : <span key={task.id} className="randall-start-point is-unavailable" title={task.hint || undefined}>
      <TaskIcon task={task} size={15} /><span>{task.label}</span><span className="randall-task-soon">Use MCP</span></span>
  return <div className={`randall-start-points${away ? ' is-away' : ''}`} inert={away || undefined}>
    {groupTasks(tasks).map((group, index) => <div key={group.name || index} className="randall-start-group"
      role={group.name ? 'group' : undefined} aria-label={group.name || undefined}>
      {group.name && <span className="randall-start-group-label" aria-hidden="true">{group.name}</span>}
      <div className="randall-start-row">{group.tasks.map(chip)}</div>
    </div>)}
  </div>
}

// After a finished task: the same-chat next step (if the task has one), then the
// startable tasks as small chips for a new chat under their own "Start another" label.
export function StartAnother({ tasks, onPick, disabled, followUp, onFollowUp }) {
  return <div className="randall-task-again">
    {followUp && <button type="button" className="randall-task-followup" disabled={disabled}
      onClick={() => onFollowUp(followUp.draft)}>{followUp.label}</button>}
    <div className="randall-task-again-group" role="group" aria-label="Start another">
      <span className="randall-task-again-label" aria-hidden="true">Start another</span>
      <div className="randall-task-tiles randall-task-tiles--compact">
        {tasks.filter(isStartable).map(task => <button key={task.id} type="button" className="randall-task-tile" disabled={disabled}
          title={task.hint} onClick={() => onPick(task.id)}><strong>{task.label}</strong></button>)}
      </div>
    </div>
  </div>
}

export function TaskMismatch({ label, onStart, disabled }) {
  return <div className="randall-task-mismatch">
    <button type="button" className="randall-task-switch" disabled={disabled} onClick={onStart}>New chat: {label}
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
    </button>
  </div>
}
