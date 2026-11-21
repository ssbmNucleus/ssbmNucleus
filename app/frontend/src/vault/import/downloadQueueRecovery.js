export const recoverFailedDownload = ({ phase, recoveryAvailable, pending, current }, action) => {
  if (phase !== 'error' || !recoveryAvailable) {
    return { accepted: false, pending }
  }

  if (action === 'retry') return { accepted: true, pending: current ? [current, ...pending] : [...pending] }
  if (action === 'cancel') return { accepted: true, pending: [] }
  if (action === 'skip') return { accepted: true, pending: [...pending] }
  throw new Error(`Unknown download recovery action: ${action}`)
}
