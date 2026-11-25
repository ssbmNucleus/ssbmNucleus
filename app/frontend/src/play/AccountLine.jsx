import { useEffect, useState } from 'react'
import { api } from '../shared/transport/api'

/** The Slippi account the games sign in with (GET /api/play/account): name and code only. */
export default function AccountLine({ visible = true }) {
  const [account, setAccount] = useState(null)

  useEffect(() => {
    if (!visible) return undefined
    let live = true
    api.get('/api/play/account')
      .then((data) => { if (live) setAccount(data) })
      .catch(() => { if (live) setAccount({ signedIn: false }) })
    return () => { live = false }
  }, [visible])

  if (!account) return <p className="play-account" aria-busy="true">&nbsp;</p>
  if (!account.signedIn) {
    return (
      <p className="play-account play-account--none">
        No Slippi account found. Sign in once with the Slippi Launcher; your games use the same account.
      </p>
    )
  }
  return (
    <p className="play-account">
      Slippi: <strong>{account.displayName || 'Signed in'}</strong>
      {account.connectCode && <span className="play-account-code">{account.connectCode}</span>}
    </p>
  )
}
