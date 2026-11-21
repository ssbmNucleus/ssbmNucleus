import { useEffect, useState } from 'react'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { getAccount, onAccountChange, signIn, signOut, REGISTER_URL, RESET_PASSWORD_URL } from '../shared/account/account'
import { getEntitlement, clearPatreonToken, buildPatreonAuthorizeUrl, openExternal, ENTITLEMENT_EVENT, PATREON_CAMPAIGN_URL } from '../shared/account/entitlement'
import { patreonMembershipLabel, isPatreonNonMember } from '../shared/account/membershipLabel'
import { isCloudPaid } from '../shared/account/cloudPlan'
import PatreonIcon from '../shared/account/PatreonIcon'
import { getStartggSlug, setStartggSlug, parseSlug, fetchStartggProfile, clearStartggCache } from '../tracker/tournaments/startgg'
import { NUCLEOME_ENABLED } from '../shared/config/features'
import { api } from '../shared/transport/api'
import { discordAfterPollFailure } from './discordState'
import './AccountSection.css'

const DISCORD_API = '/api/account/discord'

// Discord's controller-face mark, simplified
const DiscordIcon = props => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true" {...props}>
    <path d="M19.6 5.3A16 16 0 0 0 15.7 4l-.5 1a15 15 0 0 0-6.4 0l-.5-1a16 16 0 0 0-3.9 1.3C2 9 1.4 12.6 1.7 16.1A16 16 0 0 0 6.5 18.6l1-1.5a10 10 0 0 1-1.6-.8l.4-.3a11.5 11.5 0 0 0 11.4 0l.4.3-1.6.8 1 1.5a16 16 0 0 0 4.8-2.5c.4-4-.7-7.6-2.7-10.8ZM8.7 14c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2Zm6.6 0c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2Z" />
  </svg>
)

// A tournament-bracket glyph for start.gg
const StartggIcon = props => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <path d="M8 4H5v16h3M16 4h3v16h-3" />
  </svg>
)

/**
 * Account settings — two SEPARATE accounts, one per row:
 *   1. Nucleus (ssbmnucleus.net) — unlocks publishing from the Upload tab.
 *   2. Patreon — a distinct account, and the sign-in for anything that touches
 *      our servers. A FREE $0 account is enough to share single replays; any
 *      paid tier ($5 and up) adds the phone app and whole-library sync (and
 *      Randall). Shown in BOTH Nucleus and nucleOME modes so it always reads
 *      as its own thing, not a property of the Nucleus login. Settings > Cloud
 *      is where the cloud side is sold and explained; this row is the account.
 *
 * Patreon is fully independent of the Nucleus account: linking starts in the
 * browser (buildPatreonAuthorizeUrl → the website's /patreon/callback), which
 * mints an app token and deep-links it back (nucleus://patreon-link). The
 * token lives in localStorage and authenticates ai-entitlement directly —
 * no Nucleus sign-in involved at any point.
 */
export default function AccountSection({ nucleome = false }) { // eslint-disable-line no-unused-vars
  const [account, setAccount] = useState(null)
  const [checking, setChecking] = useState(true)
  // undefined = loading; object = ai-entitlement response
  const [ent, setEnt] = useState(undefined)
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showEmail, setShowEmail] = useState(false)
  const [avatarFailed, setAvatarFailed] = useState(false)
  const [patreonAvatarFailed, setPatreonAvatarFailed] = useState(false)
  const [startgg, setStartgg] = useState(getStartggSlug())
  const [startggInput, setStartggInput] = useState('')
  const [startggProfile, setStartggProfile] = useState(null)
  const [startggAvatarFailed, setStartggAvatarFailed] = useState(false)
  // Discord: the BACKEND owns that session (publishing and bug reports use
  // it), so this row just mirrors GET /api/account/discord.
  const [discord, setDiscord] = useState(undefined) // undefined = loading; null = unreachable
  const [discordAvatarFailed, setDiscordAvatarFailed] = useState(false)

  // Fresh session -> email hidden again, avatars retried.
  useEffect(() => {
    setShowEmail(false)
    setAvatarFailed(false)
    setPatreonAvatarFailed(false)
  }, [account?.id])

  // Another Discord account (or a new avatar) gets its own image attempt.
  useEffect(() => { setDiscordAvatarFailed(false) }, [discord?.account?.user_id, discord?.account?.avatar_url])

  useEffect(() => {
    let mounted = true
    getAccount()
      .then(value => { if (mounted) setAccount(value) })
      .catch(() => {})
      .finally(() => { if (mounted) setChecking(false) })
    const unsubscribe = onAccountChange(value => { if (mounted) setAccount(value) })
    return () => { mounted = false; unsubscribe() }
  }, [])

  const refreshDiscord = () =>
    api.get(DISCORD_API)
      .then(d => {
        setDiscord({ account: d.account, auth: d.auth })
        // App.jsx mirrors this account for the Upload tab.
        window.dispatchEvent(new Event('discord-account-changed'))
      })
      // A failed poll during a sign-in keeps the pending state, which is what
      // keeps polling; otherwise the row would vanish until the next focus.
      .catch(() => setDiscord(discordAfterPollFailure))

  useEffect(() => {
    if (!NUCLEOME_ENABLED) return undefined
    refreshDiscord()
    // The OAuth hop happens in the system browser; re-check on focus, and
    // poll while a sign-in is in flight so the row flips on its own.
    window.addEventListener('focus', refreshDiscord)
    const t = setInterval(() => {
      if (document.hidden) return
      setDiscord(d => { if (d?.auth?.state === 'pending') refreshDiscord(); return d })
    }, 2000)
    return () => { window.removeEventListener('focus', refreshDiscord); clearInterval(t) }
  }, [])

  const discordSignIn = async () => {
    playSound('boop')
    try {
      const d = await api.post(`${DISCORD_API}/start`)
      if (d.url && window.electron?.openExternal) window.electron.openExternal(d.url)
      setDiscord({ account: d.account, auth: d.auth })
    } catch (err) {
      setError(err.message || 'Could not start the Discord sign-in')
    }
  }

  const discordSignOut = async () => {
    playSound('back')
    try {
      const d = await api.post(`${DISCORD_API}/signout`)
      setDiscord({ account: d.account, auth: d.auth })
      window.dispatchEvent(new Event('discord-account-changed'))
    } catch { /* the next refresh tells the truth */ }
  }

  const submit = async event => {
    event.preventDefault()
    if (busy || !identifier.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      await signIn(identifier, password)
      setIdentifier('')
      setPassword('')
      playSound('start')
    } catch (err) {
      setError(err.message || 'Sign-in failed')
      playSound('back')
    } finally {
      setBusy(false)
    }
  }

  const handleSignOut = async () => {
    playSound('back')
    try { await signOut() } catch { /* session already gone */ }
  }

  const connectStartgg = event => {
    event.preventDefault()
    const slug = parseSlug(startggInput)
    if (!slug) return
    setStartggSlug(slug)
    setStartgg(slug)
    setStartggInput('')
    playSound('start')
  }

  // Patreon membership status — account-independent (keyed by the stored app
  // token). Re-checks on window focus (the OAuth link happens in the browser)
  // and on entitlement events (deep-link handoff, local Patreon sign-out).
  useEffect(() => {
    if (!NUCLEOME_ENABLED) return undefined // guard kept for a future re-gate; shipped builds poll
    let mounted = true
    setEnt(undefined)
    const check = force => getEntitlement(force ? { force: true } : undefined)
      .then(value => { if (mounted) setEnt(value) })
      .catch(() => { if (mounted) setEnt({ checkFailed: true }) })
    check(false)
    const onFocus = () => check(true)
    window.addEventListener('focus', onFocus)
    window.addEventListener(ENTITLEMENT_EVENT, onFocus)
    return () => {
      mounted = false
      window.removeEventListener('focus', onFocus)
      window.removeEventListener(ENTITLEMENT_EVENT, onFocus)
    }
  }, [])

  // Resolve the connected start.gg slug to a gamertag + PFP (backend holds the token).
  useEffect(() => {
    if (!NUCLEOME_ENABLED || !startgg) { setStartggProfile(null); return undefined }
    let live = true
    setStartggAvatarFailed(false)
    fetchStartggProfile(startgg).then(p => { if (live) setStartggProfile(p) })
    return () => { live = false }
  }, [startgg])

  // Only the NOT-linked branch of the row renders this now, so the linked
  // cases are just fallbacks for a check that hasn't landed yet.
  const entLabel = ent === undefined ? 'Checking…'
    : ent?.linked ? `Linked as ${ent.patreon_name || 'your Patreon'}`
    : ent?.checkFailed ? 'Patreon check failed'
    : 'Not linked'

  // Patreon PFP, once the ai-entitlement edge fn forwards Patreon's image_url
  // (defensive on field name); falls back to the name's initial like the
  // Nucleus avatar does.
  const patreonAvatar = ent?.patreon_avatar_url || ent?.patreon_thumb_url || ent?.patreon_image_url || ''

  return (
    <section className="settings-section account-section">
      <h3>Account</h3>

      {/* Row 1 — Nucleus (ssbmnucleus.net) account */}
      <div className="account-provider">
        <span className="account-provider-label">Nucleus account</span>
        {checking ? (
          <p className="section-description">Checking session…</p>
        ) : account ? (
          <div className="account-signed-in">
            <div className="account-avatar">
              {account.avatarUrl && !avatarFailed ? (
                <img src={account.avatarUrl} alt="" onError={() => setAvatarFailed(true)} />
              ) : (
                (account.username || '?')[0].toUpperCase()
              )}
            </div>
            <div className="account-identity">
              <strong>{account.username}</strong>
              <button
                type="button"
                className="account-email"
                title={showEmail ? 'Click to hide your email' : 'Click to show your email'}
                onClick={() => setShowEmail(current => !current)}
              >
                {showEmail ? account.email : 'Show email'}
              </button>
            </div>
            <button type="button" className="account-signout" onMouseEnter={playHoverSound} onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        ) : (
          <>
            <p className="section-description">
              Sign in with your ssbmnucleus.net account, or link Discord below — either one lets you publish from the Upload tab.
            </p>
            <form className="account-form" onSubmit={submit}>
              <input
                value={identifier}
                onChange={event => setIdentifier(event.target.value)}
                placeholder="Username or email"
                autoComplete="username"
              />
              <input
                type="password"
                value={password}
                onChange={event => setPassword(event.target.value)}
                placeholder="Password"
                autoComplete="current-password"
              />
              {error && <p className="account-error">{error}</p>}
              <button
                type="submit"
                className="account-signin"
                disabled={busy || !identifier.trim() || !password}
                onMouseEnter={playHoverSound}
              >
                {busy ? 'Signing in…' : 'Sign In'}
              </button>
            </form>
            <p className="account-links">
              <button type="button" onClick={() => openExternal(REGISTER_URL)}>Create an account</button>
              <span>&middot;</span>
              <button type="button" onClick={() => openExternal(RESET_PASSWORD_URL)}>Forgot password?</button>
            </p>
          </>
        )}
      </div>

      {/* Rows 2 and 3 are nucleOME surfaces — Patreon signs the vault in and
          start.gg feeds the tournaments tab — so they stay hidden until
          nucleOME ships. See shared/config/features.js. */}
      {NUCLEOME_ENABLED && <>
      {/* Row 2 — Discord. Session lives in the backend (shared/account);
          publishing and bug reports use it. This row mirrors it. */}
      {discord !== null && (
        <div className="account-provider account-discord-provider">
          <span className="account-provider-label"><DiscordIcon /> Discord</span>
          {discord?.account ? (
            <div className="account-signed-in">
              <div className="account-avatar account-discord-avatar">
                {discord.account.avatar_url && !discordAvatarFailed ? (
                  <img src={discord.account.avatar_url} alt="" referrerPolicy="no-referrer" onError={() => setDiscordAvatarFailed(true)} />
                ) : (
                  (discord.account.username || 'D')[0].toUpperCase()
                )}
              </div>
              <div className="account-identity">
                <strong>{discord.account.username || 'Discord'}</strong>
                <span className="account-patreon-sub">
                  {discord.account.discord_username ? `@${discord.account.discord_username}` : 'Signed in with Discord'}
                </span>
              </div>
              <button
                type="button"
                className="account-signout"
                title="Sign out of Discord in this app"
                onMouseEnter={playHoverSound}
                onClick={discordSignOut}
              >
                Sign out
              </button>
            </div>
          ) : (
            <div className="account-provider-body">
              <span className="account-patreon-status">
                {discord === undefined ? 'Checking…'
                  : discord?.auth?.state === 'pending' ? 'Waiting for Discord in your browser…'
                    : discord?.auth?.state === 'error' ? `Sign-in failed: ${discord.auth.error}`
                      : 'Not linked'}
              </span>
              <button
                type="button"
                className="account-discord-btn"
                disabled={discord === undefined || discord?.auth?.state === 'pending'}
                onMouseEnter={playHoverSound}
                onClick={discordSignIn}
              >
                <DiscordIcon /> Sign in with Discord
              </button>
            </div>
          )}
        </div>
      )}

      {/* Row 3 — Patreon: mirrors the Nucleus account row (avatar + name).
          Keyed on `linked`, NOT `active`: a free ($0) account is a real
          sign-in that shares single replays, so showing it the "Link Patreon"
          button would tell a signed-in user they were signed out. The paid
          tier (isCloudPaid, not AI `active`) only decides the tier sub-label
          and which button sits next to it. */}
      <div className="account-provider account-patreon-provider">
        <span className="account-provider-label"><PatreonIcon /> Patreon</span>
        {ent?.linked ? (
          <div className="account-signed-in">
            <div className="account-avatar account-patreon-avatar">
              {patreonAvatar && !patreonAvatarFailed ? (
                <img src={patreonAvatar} alt="" onError={() => setPatreonAvatarFailed(true)} />
              ) : (
                (ent.patreon_name || 'P')[0].toUpperCase()
              )}
            </div>
            <div className="account-identity">
              <strong>{ent.patreon_name || 'Patreon'}</strong>
              <span className="account-patreon-sub">{patreonMembershipLabel(ent)}</span>
            </div>
            <button
              type="button"
              className="account-signout"
              title={isCloudPaid(ent)
                ? 'Open your membership on Patreon (change or upgrade your tier)'
                : isPatreonNonMember(ent)
                  ? "Join sc00p's Patreon for free (not just Follow), then Re-link so Nucleus sees it"
                  : 'See the Patreon tiers ($5/month and up adds your whole library on your phone)'}
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); openExternal(PATREON_CAMPAIGN_URL) }}
            >
              {isCloudPaid(ent) ? 'Manage' : isPatreonNonMember(ent) ? 'Join free' : 'View tiers'}
            </button>
            {/* Re-link without signing out: patreon-link re-reads the membership
                and mints a new token (the old one keeps working for a while). */}
            <button
              type="button"
              className="account-signout"
              title="Link Patreon again to refresh your membership (no need to sign out)"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); openExternal(buildPatreonAuthorizeUrl()) }}
            >
              Re-link
            </button>
            <button
              type="button"
              className="account-signout"
              title="Sign out of Patreon in this app (re-link any time)"
              onMouseEnter={playHoverSound}
              onClick={() => {
                playSound('back')
                clearPatreonToken() // the ENTITLEMENT_EVENT re-check resets the row
              }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <div className="account-provider-body">
            <span className="account-patreon-status" title={entLabel}>{entLabel}</span>
            <button
              type="button"
              className="account-patreon-btn"
              onMouseEnter={playHoverSound}
              onClick={() => {
                playSound('boop')
                openExternal(buildPatreonAuthorizeUrl())
              }}
            >
              <PatreonIcon /> Link Patreon
            </button>
          </div>
        )}
      </div>

      {/* Row 4 — start.gg: your public tournament profile (no OAuth needed) */}
      <div className="account-provider account-startgg-provider">
        <span className="account-provider-label"><StartggIcon /> start.gg</span>
        {startgg ? (
          <div className="account-signed-in">
            <div className="account-avatar account-startgg-avatar">
              {startggProfile?.image && !startggAvatarFailed ? (
                <img src={startggProfile.image} alt="" onError={() => setStartggAvatarFailed(true)} />
              ) : (
                (startggProfile?.gamer_tag || startgg)[0].toUpperCase()
              )}
            </div>
            <div className="account-identity">
              <strong>{startggProfile?.gamer_tag || startgg}</strong>
              {/* deliberately no real name here — gamer tag + PFP only */}
              <span className="account-patreon-sub">start.gg profile</span>
            </div>
            <button
              type="button"
              className="account-signout"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); clearStartggCache(startgg); setStartggSlug(''); setStartgg(''); setStartggProfile(null) }}
            >
              Disconnect
            </button>
          </div>
        ) : (
          <form className="account-form account-startgg-form" onSubmit={connectStartgg}>
            <input
              value={startggInput}
              onChange={event => setStartggInput(event.target.value)}
              placeholder="Your start.gg profile URL or slug"
              autoComplete="off"
            />
            <button
              type="submit"
              className="account-startgg-btn"
              disabled={!startggInput.trim()}
              onMouseEnter={playHoverSound}
            >
              <StartggIcon /> Connect start.gg
            </button>
          </form>
        )}
      </div>
      </>}
    </section>
  )
}
