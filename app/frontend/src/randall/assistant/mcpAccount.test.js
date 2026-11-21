import test from 'node:test'
import assert from 'node:assert/strict'
import { createMcpAccountMirror, createMcpWindowMirror } from './mcpAccount.js'

test('the mirror sends the current Patreon token, and null once signed out', async () => {
  let token = 'patreon-app-token'
  const sent = []
  const mirror = createMcpAccountMirror({ getToken: () => token, post: async body => { sent.push(body) } })
  await mirror()
  token = ''
  await mirror()
  assert.deepEqual(sent, [{ token: 'patreon-app-token' }, { token: null }])
})

test('a backend that cannot be reached does not break the window', async () => {
  const mirror = createMcpAccountMirror({ getToken: () => 't', post: async () => { throw new Error('down') } })
  await mirror()
})

test('the window mirror sends the Settings Dolphin folder, and null once cleared', async () => {
  let folder = 'C:/Slippi/netplay'
  const sent = []
  const mirror = createMcpWindowMirror({ getDolphinPath: () => folder, post: async body => { sent.push(body) } })
  await mirror()
  folder = ''
  await mirror()
  assert.deepEqual(sent, [{ slippi_dolphin_path: 'C:/Slippi/netplay' }, { slippi_dolphin_path: null }])
  await createMcpWindowMirror({ getDolphinPath: () => 'x', post: async () => { throw new Error('down') } })()
})

test('the confirm watcher asks each open question once and sends the answer the person gave', async () => {
  const { createMcpConfirmWatcher } = await import('./mcpAccount.js')
  let pending = [{ id: 'a', title: 'Connect?', message: 'm' }]
  const asked = []
  const answered = []
  let refresh
  const stop = createMcpConfirmWatcher({
    list: async () => ({ pending }),
    ask: async (item) => { asked.push(item.id); return item.id === 'a' },
    answer: async (id, allowed) => { answered.push([id, allowed]) },
    subscribe: (fn) => { refresh = fn; return () => { refresh = null } },
  })
  await new Promise(resolve => setTimeout(resolve, 0))
  pending = [{ id: 'a' }, { id: 'b' }]
  await refresh()
  await refresh()
  assert.deepEqual(asked, ['a', 'b'])
  assert.deepEqual(answered, [['a', true], ['b', false]])
  stop()
  assert.equal(refresh, null)
})

test('the confirm watcher survives a backend that is down and a dialog that fails', async () => {
  const { createMcpConfirmWatcher } = await import('./mcpAccount.js')
  const answered = []
  let refresh
  createMcpConfirmWatcher({
    list: async () => { throw new Error('down') },
    ask: async () => true, answer: async () => {}, subscribe: (fn) => { refresh = fn; return () => {} },
  })
  createMcpConfirmWatcher({
    list: async () => ({ pending: [{ id: 'x' }] }),
    ask: async () => { throw new Error('no dialog host') },
    answer: async (id, allowed) => { answered.push([id, allowed]) },
    subscribe: () => () => {},
  })
  await refresh()
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.deepEqual(answered, [['x', false]])               // a failed dialog is a no, never a yes
})
