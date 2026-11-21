// The chat sidebar's list (ChatSidebar in ChatUI.jsx): search, date groups and
// paging. Pure: no React. Both stores list newest first with a REAL epoch-seconds
// time: the assistant's `updated`, the coach's `updated_at`.

const DAY = 24 * 60 * 60 * 1000
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** When the chat last changed, in ms, or null. */
export function chatTime(chat) {
  const seconds = Number(chat?.updated ?? chat?.updated_at)
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : null
}

/** Chats whose title contains `query` (trimmed, any case); every chat for an empty query. */
export function filterChats(chats, query) {
  const q = String(query || '').trim().toLowerCase()
  const list = Array.isArray(chats) ? chats : []
  return q ? list.filter((chat) => String(chat?.title || '').toLowerCase().includes(q)) : list
}

const startOfDay = (ms) => { const day = new Date(ms); day.setHours(0, 0, 0, 0); return day.getTime() }

/**
 * The date heading for a chat changed at `ms`, seen at `now` (local time): Today,
 * Yesterday, the weekday within the last week, "Sep 28" within the last 30 days,
 * else Older. A chat with no time is Older.
 */
export function dateLabel(ms, now = Date.now()) {
  if (ms === null || ms === undefined) return 'Older'
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / DAY)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  const date = new Date(ms)
  if (days < 7) return WEEKDAYS[date.getDay()]
  if (days < 30) return `${MONTHS[date.getMonth()]} ${date.getDate()}`
  return 'Older'
}

/** `[{label, chats}]` in list order: consecutive chats under the same heading share a group. */
export function groupChats(chats, now = Date.now()) {
  const groups = []
  for (const chat of Array.isArray(chats) ? chats : []) {
    const label = dateLabel(chatTime(chat), now)
    const last = groups.at(-1)
    if (last && last.label === label) last.chats.push(chat)
    else groups.push({ label, chats: [chat] })
  }
  return groups
}

/**
 * The first `shown` chats (never hiding the open one), and how many the "Show N
 * more" link adds next: up to `step` of the rest. -> {visible, more}
 */
export function pageChats(chats, shown, activeId = null, step = shown) {
  const list = Array.isArray(chats) ? chats : []
  const active = activeId === null || activeId === undefined ? -1 : list.findIndex((chat) => chat?.id === activeId)
  const count = Math.min(list.length, Math.max(shown, active + 1))
  return { visible: list.slice(0, count), more: Math.min(step, list.length - count) }
}
