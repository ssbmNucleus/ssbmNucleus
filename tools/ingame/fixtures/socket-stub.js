// Stands in for app/frontend/src/shared/transport/socket.js in the ISO import smoke.
// The fixture server has no Socket.IO, so this polls its GET /api/jobs and hands
// each record to the `job` handlers, which is what the backend's socket does
// when a job changes. The job store keeps a record only when its seq is newer.
import api from '../../../app/frontend/src/shared/transport/api'

const handlers = new Set()
let timer = null

function poll() {
  api.get('/api/jobs').then((reply) => {
    for (const record of reply.jobs || []) {
      for (const map of handlers) map.job?.(record)
    }
  }).catch(() => {})
}

const idle = { on() { return idle }, off() { return idle }, emit() { return idle }, connected: false, disconnect() {} }

export function getSocket() { return idle }

export function subscribe(map) {
  handlers.add(map)
  if (!timer) timer = setInterval(poll, 25)
  return () => handlers.delete(map)
}

export function emit() {}

export function channel() { return idle }
