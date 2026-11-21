// Costume-order saves still pending anywhere in the panel, from the first
// queued drag until its batch has landed. Switch Project and Close Project wait
// for them: the moves were made in the open project and must be saved there,
// not on whichever project is open next.
let pending = 0
let waiters = []

export function orderSaveStarted() {
  pending += 1
}

export function orderSaveSettled() {
  pending = Math.max(0, pending - 1)
  if (pending > 0) return
  const done = waiters
  waiters = []
  done.forEach(resolve => resolve())
}

export function orderSavesPending() {
  return pending > 0
}

export function waitForOrderSaves() {
  return pending === 0 ? Promise.resolve() : new Promise(resolve => waiters.push(resolve))
}
