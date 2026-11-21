import assert from 'node:assert/strict'
import test from 'node:test'
import { chatTime, dateLabel, filterChats, groupChats, pageChats } from './chatList.js'

// Local noon on Friday 2026-10-02, so day arithmetic never sits on a midnight.
const NOW = new Date(2026, 9, 2, 12, 0, 0).getTime()
const at = (daysAgo, hour = 10) => { const day = new Date(NOW); day.setDate(day.getDate() - daysAgo); day.setHours(hour, 0, 0, 0); return day.getTime() / 1000 }

test('a chat’s time is either store’s epoch seconds', () => {
  assert.equal(chatTime({ updated: 1700000000.5 }), 1700000000500)
  assert.equal(chatTime({ updated_at: 1700000000 }), 1700000000000, 'the coach store')
  assert.equal(chatTime({}), null)
  assert.equal(chatTime({ updated: 'soon' }), null)
  assert.equal(chatTime(null), null)
})

test('date headings: Today, Yesterday, the weekday, the day, Older', () => {
  assert.equal(dateLabel(at(0, 1) * 1000, NOW), 'Today')
  assert.equal(dateLabel(NOW + 3600e3, NOW), 'Today', 'a clock a little ahead is still today')
  assert.equal(dateLabel(at(1, 23) * 1000, NOW), 'Yesterday')
  assert.equal(dateLabel(at(2) * 1000, NOW), 'Wednesday')
  assert.equal(dateLabel(at(6) * 1000, NOW), 'Saturday')
  assert.equal(dateLabel(at(7) * 1000, NOW), 'Sep 25')
  assert.equal(dateLabel(at(29) * 1000, NOW), 'Sep 3')
  assert.equal(dateLabel(at(30) * 1000, NOW), 'Older')
  assert.equal(dateLabel(null, NOW), 'Older')
})

test('chats group under their heading in list order', () => {
  const chats = [
    { id: 'a', updated: at(0) }, { id: 'b', updated: at(0, 8) }, { id: 'c', updated: at(1) },
    { id: 'd', updated_at: at(4) }, { id: 'e', updated: at(10) }, { id: 'f', updated: at(10, 3) },
    { id: 'g', updated: at(90) }, { id: 'h' },
  ]
  assert.deepEqual(groupChats(chats, NOW).map(group => [group.label, group.chats.map(chat => chat.id)]), [
    ['Today', ['a', 'b']], ['Yesterday', ['c']], ['Monday', ['d']], ['Sep 22', ['e', 'f']], ['Older', ['g', 'h']],
  ])
  assert.deepEqual(groupChats([], NOW), [])
  assert.deepEqual(groupChats(undefined, NOW), [])
})

test('search filters titles, any case, ignoring the edges', () => {
  const chats = [{ id: 1, title: 'Lava Bowser recolor' }, { id: 2, title: 'Import Goku' }, { id: 3, title: null }]
  assert.deepEqual(filterChats(chats, '  BOWSER ').map(chat => chat.id), [1])
  assert.deepEqual(filterChats(chats, 'o').map(chat => chat.id), [1, 2])
  assert.deepEqual(filterChats(chats, ''), chats)
  assert.deepEqual(filterChats(chats, '   '), chats)
  assert.deepEqual(filterChats(chats, 'zelda'), [])
  assert.deepEqual(filterChats(null, 'x'), [])
})

test('paging shows a page, then "Show N more" adds up to a page of the rest', () => {
  const chats = Array.from({ length: 47 }, (_, index) => ({ id: index }))
  let page = pageChats(chats, 20, null, 20)
  assert.equal(page.visible.length, 20)
  assert.equal(page.more, 20)
  page = pageChats(chats, 40, null, 20)
  assert.equal(page.visible.length, 40)
  assert.equal(page.more, 7, 'the last step is what is left')
  page = pageChats(chats, 60, null, 20)
  assert.equal(page.visible.length, 47)
  assert.equal(page.more, 0)
  // The open chat is never hidden behind "Show more".
  page = pageChats(chats, 20, 33, 20)
  assert.equal(page.visible.length, 34)
  assert.equal(page.more, 13)
  assert.equal(pageChats(chats, 20, 'missing', 20).visible.length, 20)
  assert.deepEqual(pageChats([], 20), { visible: [], more: 0 })
})
