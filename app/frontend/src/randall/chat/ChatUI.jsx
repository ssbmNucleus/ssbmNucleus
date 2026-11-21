import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Randall } from '../../shared/ui/Sprites'
import { monthlyUsage } from '../assistant/access'
import { filterChats, groupChats, pageChats } from './chatList'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import './ChatUI.css'
import './OzoneComposer.css'

export function ChatLayout({ sidebarOpen, sidebar, children, active = true, className = '', ...props }) {
  const layoutRef = useRef(null)
  useLayoutEffect(() => {
    if (!active) return
    const page = layoutRef.current?.querySelector('.coach-page')
    const bar = page?.querySelector(':scope > .coach-inputarea')
    const scroll = page?.querySelector(':scope > .coach-scroll')
    if (!bar || !scroll) return
    const measure = () => {
      // A mounted chat is display:none while another tab is open. Keep its
      // last usable spacing, and measure again before painting on return.
      // offsetHeight also avoids measuring a scaled entrance animation.
      const height = bar.offsetHeight
      if (!height || !scroll.clientHeight) return
      const atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 32
      page.style.setProperty('--chat-bar-height', `${height}px`)
      if (atBottom) scroll.scrollTop = scroll.scrollHeight
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(bar, { box: 'border-box' })
    return () => observer.disconnect()
  }, [active])
  return <div ref={layoutRef} className={`coach-layout shared-chat ${sidebarOpen ? 'is-sidebar-open' : 'is-sidebar-collapsed'} ${className}`} {...props}>
    {sidebar}{children}
  </div>
}
const icon = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
  strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
const SidebarIcon = () => <svg {...icon} width="18" height="18" strokeWidth="1.6"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
const SearchIcon = () => <svg {...icon} width="15" height="15"><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg>
const PlusIcon = () => <svg {...icon}><path d="M12 5v14M5 12h14" /></svg>
const WarnIcon = () => <svg {...icon} width="13" height="13" strokeWidth="2"><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4m0 4h.01" /></svg>
const STATUS_TEXT = { running: 'Working', error: 'Last reply failed' }

// The chat history, laid out like the Claude desktop app's sidebar: the sidebar
// toggle, a search box, "+ New" (the primary row) and any `nav` rows under it,
// then the chats as one-line rows under date headings, "Show N more", and the
// `footer` (ChatAccount) pinned under a hairline. Both chat surfaces use it.
//
// `nav`: [{id, label, icon, title?, onSelect}] extra "new X" rows (Randall's starting points).
// `statusFor(chat)`: 'running' | 'error' | null, shown in the row's dot. Only what
//   the page already knows (its open chat); every other row is the hollow dot.
// `badgeFor(chat)`: a short tag (Randall's chat task); it goes in the row's
//   tooltip and its spoken name, so every row stays one line.
// Search filters the loaded titles here, in the page (no backend search exists).
export function ChatSidebar({ children, footer, chats, activeId, onSelect, onNew, onDelete, disabled, id, sidebarOpen, onToggleSidebar,
  badgeFor, statusFor, nav = [], pageSize = 20 }) {
  const [query, setQuery] = useState('')
  const [shown, setShown] = useState(pageSize)
  useEffect(() => { setShown(pageSize) }, [query, pageSize])
  const found = filterChats(chats, query)
  const { visible, more } = pageChats(found, shown, activeId, pageSize)
  const groups = groupChats(visible)
  return <>
    <nav className="chat-rail" aria-label="Chat controls">
      {!sidebarOpen && <button aria-label="Expand sidebar" aria-expanded={false} aria-controls={id} onClick={onToggleSidebar}><SidebarIcon /></button>}
      <button aria-label="New chat" title="New chat" disabled={disabled} onClick={onNew}>+</button>
    </nav>
    {sidebarOpen && <button className="chat-sidebar-scrim" aria-label="Dismiss sidebar" onClick={onToggleSidebar} />}
    <aside className="coach-sidebar chat-sidebar" id={id} aria-label="Chat history" inert={!sidebarOpen} aria-hidden={!sidebarOpen}>
      <div className="chat-sidebar-top">
        <button type="button" className="chat-sidebar-icon" aria-label="Collapse sidebar" aria-expanded={true} aria-controls={id}
          title="Close sidebar" onClick={onToggleSidebar}><SidebarIcon /></button>
      </div>
      <label className="chat-sidebar-search"><SearchIcon />
        <input type="search" placeholder="Search" aria-label="Search chats" value={query} onChange={event => setQuery(event.target.value)} />
      </label>
      <div className="chat-sidebar-nav">
        <button type="button" className="chat-nav-row chat-nav-row--primary" disabled={disabled} onClick={onNew}><PlusIcon /><span>New</span></button>
        {nav.map(item => <button key={item.id} type="button" className="chat-nav-row" disabled={disabled} title={item.title}
          onClick={item.onSelect}>{item.icon}<span>{item.label}</span></button>)}
      </div>
      {children}
      <div className="chat-sidebar-list">
        {groups.map((group, index) => <section key={`${index}:${group.label}`} className="chat-group" aria-label={group.label}>
          <h3 className="chat-group-label">{group.label}</h3>
          {group.chats.map(chat => {
            const active = chat.id === activeId, badge = badgeFor?.(chat), status = statusFor?.(chat) || null
            const spoken = [badge, STATUS_TEXT[status]].filter(Boolean).join(', ')
            return <div key={chat.id} className={`chat-row${active ? ' is-active' : ''}`}>
              <button type="button" className="chat-row-open" disabled={disabled} aria-current={active ? 'page' : undefined}
                title={badge ? `${badge} · ${chat.title}` : chat.title} onClick={() => onSelect(chat.id)}>
                <span className={`chat-row-dot${status ? ` is-${status}` : ''}`} aria-hidden="true">{status === 'error' && <WarnIcon />}</span>
                <span className="chat-row-title">{chat.title}</span>
                {spoken && <span className="sr-only">, {spoken}</span>}
              </button>
              {onDelete && <button type="button" className="chat-row-delete" disabled={disabled} aria-label={`Delete ${chat.title}`} title="Delete chat"
                onClick={event => { event.stopPropagation(); onDelete(chat, event) }}>
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
              </button>}
            </div>
          })}
        </section>)}
        {query.trim() && found.length === 0 && <p className="chat-sidebar-empty">No chats match “{query.trim()}”</p>}
        {more > 0 && <button type="button" className="chat-show-more" onClick={() => setShown(count => count + pageSize)}>Show {more} more</button>}
      </div>
      {footer && <div className="coach-sidebar-footer">{footer}</div>}
    </aside></>
}
const CopyIcon = (props) => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
)

const CheckIcon = (props) => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
       strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
)

// Clipboard write with a legacy execCommand fallback for locked-down webviews.
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

// Copy-to-clipboard affordance under each message (Claude/GPT style).
export function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])
  const copy = async () => {
    if (!(await copyText(text))) return
    playSound('boop')
    setCopied(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopied(false), 1600)
  }
  return (
    <button
      type="button"
      className={`coach-copy ${copied ? 'is-copied' : ''}`}
      onMouseEnter={playHoverSound}
      onClick={copy}
      title={copied ? 'Copied' : 'Copy message'}
      aria-label="Copy message"
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      <span className="coach-copy-label">{copied ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

export function ChatHeader({ actions }) {
  return actions ? <div className="chat-window-actions">{actions}</div> : null
}
// The message box. Without `controls` it is one row (textarea, then send): the
// Tracker coach's. With `controls` (Randall's attach button, task pill and
// starting pick) it is the Claude app's box: the textarea on top and, inside the
// same border, a control row with `controls` at the left and send at the right.
export function ChatInput({ inputRef, value, onChange, onSend, onQueue, disabled, sendDisabled, busy, onStop, placeholder = 'Message Randall...', maxLength, lockedAction, controls }) {
  const textarea = <textarea ref={inputRef} rows={1} aria-label="Message Randall" placeholder={placeholder} value={value} disabled={disabled} maxLength={maxLength}
    onChange={event => { onChange(event.target.value); event.target.style.height = 'auto'; event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px` }}
    onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!disabled && !sendDisabled) (busy && onQueue ? onQueue : onSend)() } }}/>
  const action = lockedAction || (<button type={busy && onStop ? 'button' : 'submit'} className={busy && onStop ? 'ozone-stop' : 'ozone-send'} disabled={busy && onStop ? false : sendDisabled || disabled || busy || !value.trim()} onClick={busy && onStop ? onStop : undefined} aria-label={busy && onStop ? 'Stop response' : 'Send message'} title={busy && onStop ? 'Stop response' : 'Send message'}>
    {busy && onStop ? <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg> : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>}
  </button>)
  if (controls) {
    return <div className="ozone-composer ozone-composer--stacked">
      {textarea}
      <div className="ozone-composer-controls">
        <div className="ozone-composer-tools">{controls}</div>
        {action}
      </div>
    </div>
  }
  return <div className="ozone-composer">{textarea}{action}</div>
}

/** The composer's locked action for a linked account that is not a member of
 * sc00p's Patreon: join for free there (onJoin opens the campaign page), then
 * check again here. */
export function JoinFreeUnlock({ onJoin, onCheck }) {
  return <span className="chat-unlock-group">
    <button type="button" className="chat-unlock" onClick={onJoin} title="Open sc00p's Patreon to join for free">Join free on Patreon</button>
    <button type="button" className="chat-unlock" onClick={onCheck} title="Check your Patreon membership again">Check again</button>
  </span>
}

/** The plan label beside the name in the sidebar footer (where Claude shows "· Max"): what the Patreon link gives. */
export function planLabel(entitlement) {
  if (!entitlement || entitlement.checkFailed) return null
  if (entitlement.active) return 'Patreon'
  if (entitlement.paused) return 'Paused'
  return entitlement.linked ? 'No AI access' : 'Not linked'
}

/**
 * The usage bar: how much of this month's Patreon budget is used (`monthlyUsage`), else how much of this session's
 * cap (`usage`, the Tracker coach without one). A share and when it resets, never an amount. Null with neither.
 * A free-only person's bar is their free usage, which refills every 3 days (`monthly.free`).
 */
export function UsageMeter({ entitlement, usage, className = '' }) {
  const monthly = monthlyUsage(entitlement)
  if (!monthly && !(usage?.cap > 0)) return null
  const used = monthly ? monthly.used : Math.max(0, Math.min(1, (Number(usage.spent) || 0) / usage.cap))
  const title = !monthly ? 'AI usage this session'
    : monthly.free ? `Free Randall usage - refills ${monthly.resets}` : `Randall usage this month - resets ${monthly.resets}`
  return <div className={`coach-usage ${className}`.trim()} title={title}>
    <div className="coach-usage-bar" role="meter" aria-label={!monthly ? 'Session AI usage' : monthly.free ? 'Free AI usage' : 'Monthly AI usage'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used * 100)}><div className="coach-usage-fill" style={{width: `${used * 100}%`}} /></div>
    <span className="coach-usage-text">{monthly ? monthly.text : 'Session usage'}</span>
  </div>
}

export function ChatAccount({ entitlement, usage, name, avatar, onSettings }) {
  const who = name || entitlement?.patreon_name || 'Patreon'
  const plan = planLabel(entitlement)
  return <>
    <UsageMeter entitlement={entitlement} usage={usage} />
    <div className="coach-sidebar-account">
      {avatar ? <img className="coach-sidebar-avatar coach-sidebar-avatar--img" src={avatar} alt="" /> : <span className="coach-sidebar-avatar" aria-hidden="true">{who[0].toUpperCase()}</span>}
      <span className="coach-sidebar-user"><span className="coach-sidebar-name">{who}</span>{plan && <span className="coach-sidebar-plan"> · {plan}</span>}</span>
      <button type="button" className="coach-brain" aria-label="Randall settings" title="Randall settings" onClick={onSettings}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--chat-sidebar-bg, var(--color-bg-elevated))"/><circle cx="15" cy="17" r="3" fill="var(--chat-sidebar-bg, var(--color-bg-elevated))"/></svg>
      </button>
    </div>
  </>
}

export function RandallIdentity() {
  return <div className="chat-speaker" role="img" aria-label="Randall"><Randall size={26} /></div>
}

export function TypingBubble() {
  return <div className="coach-msg coach-msg--assistant assistant-typing" role="status" aria-label="Randall is working">
    <span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" />
  </div>
}
