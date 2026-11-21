import { UsageMeter } from '../chat/ChatUI'
import { monthlyUsage } from './access'

/** Randall settings' usage row: the chat sidebar's bar for this month, and when it resets. Never an amount. */
export default function UsageRow({ entitlement }) {
  const usage = monthlyUsage(entitlement)
  return <div className="assistant-settings-row"><span className="assistant-sidebar-label">Usage</span>
    {usage ? <>
      <UsageMeter entitlement={entitlement} className="assistant-settings-usage" />
      {!usage.limitReached && <p className="assistant-settings-reset">{usage.free ? 'Free usage refills' : 'Resets'} {usage.resets}.</p>}
    </> : <>
      <strong>Not reported</strong>
      <p>Your monthly usage shows here once Patreon reports it.</p>
    </>}
  </div>
}
