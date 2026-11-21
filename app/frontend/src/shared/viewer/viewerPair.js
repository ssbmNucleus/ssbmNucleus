import { launchPaintViewerSession } from './viewerSession.js'

export function previewPairMembers(paths) {
  if (!paths.members) return null
  const members = paths.members
  if (!Array.isArray(members) || members.length !== 2 ||
      !members.some(member => member.memberId === 'popo') ||
      !members.some(member => member.memberId === 'nana') ||
      members.some(member => !member.datFile) || members[0].datFile === members[1].datFile) {
    throw new Error('The Ice Climbers preview requires both Popo and Nana.')
  }
  return members.map(({ memberId, datFile, sceneFile, ajFile, dataFile }) =>
    ({ memberId, datFile, sceneFile, ajFile, dataFile }))
}

// Ready means BOTH models loaded, including when native events arrive before
// viewerStart resolves. A reconnect cannot inherit the previous pair's reply.
export async function launchPreviewSession(options) {
  const members = previewPairMembers(options.paths)
  if (!members) return launchPaintViewerSession(options)
  const sessionId = options.paths.viewerSessionId
  const requestId = `${sessionId}:preview-pair`
  let sent = false, settled = false, timer, dispose
  let finish
  const loaded = new Promise(resolve => { finish = resolve })
  const settle = result => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    finish(result)
  }
  timer = setTimeout(() => settle({ error: 'Loading Popo and Nana timed out. Retry to reconnect.' }), 30000)
  const result = await launchPaintViewerSession({ ...options,
    onSubscribe: cleanup => {
      dispose = () => { cleanup(); settle({ cancelled: true }) }
      options.onSubscribe(dispose)
    },
    onMessage: message => {
      if (message.type === 'ready') {
        if (sent) return
        sent = true
        Promise.resolve(options.electron.viewerSend({ type: 'loadPaintPair', preview: true,
          sessionId, requestId, members,
          primaryMemberId: members.find(member => member.datFile === options.paths.datFile)?.memberId || 'popo' })).then(value => {
          if (value === false) settle({ error: 'Viewer disconnected before loading both climbers.' })
        }).catch(error => settle({ error: error.message }))
      } else if (message.type === 'paintPairLoaded') {
        if (settled || message.sessionId !== sessionId || message.requestId !== requestId) return
        if (!message.success) settle({ error: message.error || 'Could not load both climbers.' })
        else {
          settle({})
          options.onMessage({ ...message, type: 'ready' })
        }
      } else {
        if (message.type === 'disconnected') settle({ error: message.error || 'Viewer connection lost.' })
        options.onMessage(message)
      }
    }
  }).catch(error => { dispose?.(); throw error })
  if (!result) { dispose?.(); return null }
  const outcome = await loaded
  if (outcome.cancelled || !options.isCurrent()) return null
  if (outcome.error) {
    dispose?.()
    await options.electron.viewerStop?.(sessionId)
    throw new Error(outcome.error)
  }
  return result
}
