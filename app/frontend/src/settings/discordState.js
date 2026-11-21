/** A transient poll failure must preserve the pending attempt that drives retries. */
export function discordAfterPollFailure(current) {
  return current?.auth?.state === 'pending' ? current : null
}
