/**
 * CloudHero - the card at the top of Settings > Cloud. It says what the cloud
 * gives you at your Patreon level, then offers the one next step, right here:
 * link Patreon, join free, get the $5 tier, pair your phone, or renew.
 *
 * Product rules it follows: sharing single replays is free (a $0 Patreon
 * account is enough), the phone app and whole-library sync are $5 and up, and
 * every paid tier unlocks the same cloud features.
 *
 * The tone is an explanation, not an ad: one card, one next step, no badges
 * or banners. Someone without the phone tier sees one line, a real
 * screenshot of the phone app and the Patreon button; a paying user just sees
 * their tier and the phone pairing.
 *
 * Patreon happens in the browser. A click that sends someone there arms a
 * one-shot re-check for when this window gets focus back, so pledging or
 * joining shows up on return without anyone pressing a button.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import {
  buildPatreonAuthorizeUrl, openExternal, recheckEntitlement, PATREON_CAMPAIGN_URL,
} from '../../shared/account/entitlement'
import { PHONE_PRICE } from '../../shared/account/cloudPlan'
import PatreonIcon from '../../shared/account/PatreonIcon'
import PhonePairing from './PhonePairing'
import './CloudHero.css'

// Through import.meta.glob, not a plain import: the public source drop leaves this
// screenshot out (it shows stock and stage icons; tools/public_drop.py), and a plain
// import would stop a clone's frontend build. Without it the hero has no picture.
const phoneShot = Object.values(import.meta.glob('./phone-games.webp', { eager: true, import: 'default' }))[0]

const PHONE_ADDRESS = 'tracker.ssbmnucleus.net'

const Check = () => (
  <svg className="cloud-hero-check" viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true"
       stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 6 9 17l-5-5" />
  </svg>
)

const PITCH = 'Sync your replays to your phone!'

// A real screenshot of the phone app's Games tab, taken with a placeholder
// library (made-up tags, no real player). Decorative: the title says the
// same thing for screen readers.
const PhoneShot = () => (phoneShot ? (
  <div className="cloud-hero-shot" aria-hidden="true">
    <img src={phoneShot} alt="" draggable="false" />
  </div>
) : null)

function formatDay(iso) {
  const d = new Date(iso)
  return Number.isFinite(d.getTime())
    ? d.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })
    : 'the end of your paid month'
}

export default function CloudHero({ plan, devices, configured, onPaired, onRevoke, entVersion }) {
  const awaiting = useRef(false)
  const [rechecking, setRechecking] = useState(false)

  // A fresh answer from Patreon (any change to the entitlement) ends the wait.
  useEffect(() => { setRechecking(false) }, [entVersion])

  useEffect(() => {
    const onFocus = () => {
      if (!awaiting.current) return
      awaiting.current = false
      setRechecking(true)
      recheckEntitlement()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  const toPatreon = (url) => {
    playSound('boop')
    awaiting.current = true
    openExternal(url)
  }
  const linkPatreon = () => toPatreon(buildPatreonAuthorizeUrl())
  const openMembership = () => toPatreon(PATREON_CAMPAIGN_URL)
  const checkAgain = () => {
    playSound('boop')
    setRechecking(true)
    recheckEntitlement()
  }

  const state = plan?.state || 'checking'
  const button = (label, onClick, { primary = true, icon = true } = {}) => (
    <button type="button" className={`cloud-hero-cta ${primary ? '' : 'is-secondary'}`}
            onMouseEnter={playHoverSound} onClick={onClick}>
      {icon && <PatreonIcon width="13" height="13" />} {label}
    </button>
  )
  const recheckLink = (label) => (
    <button type="button" className="cloud-hero-textbtn" disabled={rechecking}
            onMouseEnter={playHoverSound} onClick={checkAgain}>
      {rechecking ? 'Checking Patreon…' : label}
    </button>
  )

  let body = null
  let side = null

  if (state === 'checking') {
    body = <p className="cloud-hero-lede">Checking your Patreon…</p>
  } else if (state === 'unknown') {
    body = (
      <>
        <h3 className="cloud-hero-title">Couldn’t check your Patreon</h3>
        <p className="cloud-hero-lede">Nucleus can’t reach Patreon right now, so it doesn’t know what your account includes. Everything on this computer still works.</p>
        <div className="cloud-hero-actions">{recheckLink('Try again')}</div>
      </>
    )
  } else if (state === 'signed_out') {
    body = (
      <>
        <h3 className="cloud-hero-title">{PITCH}</h3>
        <div className="cloud-hero-actions">
          {button(`Get it on Patreon — $${PHONE_PRICE}/month`, openMembership)}
          {button('Already a member? Link Patreon', linkPatreon, { primary: false, icon: false })}
        </div>
      </>
    )
    side = <PhoneShot />
  } else if (state === 'non_member') {
    body = (
      <>
        <p className="cloud-hero-eyebrow">Patreon linked</p>
        <h3 className="cloud-hero-title">One step left: join for free</h3>
        <p className="cloud-hero-lede">
          Your Patreon is linked, but it isn’t a member of sc00p’s Patreon yet.
          Following doesn’t count: choose <strong>Join</strong> on the free tier,
          then link Patreon again here so Nucleus sees it. Joining free lets you share replays.
        </p>
        <div className="cloud-hero-actions">
          {button('Join free on Patreon', openMembership)}
          {button('Link Patreon again', linkPatreon, { primary: false })}
        </div>
      </>
    )
  } else if (state === 'free') {
    body = (
      <>
        <h3 className="cloud-hero-title">{PITCH}</h3>
        <div className="cloud-hero-actions">
          {button(`Get it on Patreon — $${PHONE_PRICE}/month`, openMembership)}
          {recheckLink('Already pledged? Check again')}
        </div>
      </>
    )
    side = <PhoneShot />
  } else if (state === 'paid') {
    const title = plan.graceUntil
      ? `You’re paid up until ${formatDay(plan.graceUntil)}`
      : `You’re on ${plan.tier?.name || 'a paid tier'}${plan.tier ? ` ($${plan.tier.price}/month)` : ''}`
    body = (
      <>
        <h3 className="cloud-hero-title"><Check /> {title}</h3>
        <p className="cloud-hero-lede">
          {plan.graceUntil
            ? 'Your membership was cancelled; your phone and syncing keep working until then.'
            : 'Your games upload to your cloud library while Nucleus is open, and your phone reads them from there.'}
        </p>
        {plan.graceUntil && (
          <div className="cloud-hero-actions">{button('Renew on Patreon', openMembership, { primary: false })}</div>
        )}
        <h4 className="cloud-hero-subhead">{devices.length ? 'Your phones' : 'Pair your phone'}</h4>
        {configured ? (
          <PhonePairing devices={devices} canPair onPaired={onPaired} onRevoke={onRevoke} />
        ) : (
          <p className="cloud-hero-fine">Getting your cloud library ready…</p>
        )}
      </>
    )
    // The steps stay up until a phone has actually opened the library, so a
    // pairing in progress (the device row exists, never seen) keeps them.
    if (!devices.some((d) => d.last_seen_at)) {
      side = (
        <ol className="cloud-hero-steps">
          <li>On your phone, open <span className="cloud-hero-address">{PHONE_ADDRESS}</span> and add it to your Home Screen.</li>
          <li>Open it from the Home Screen and tap <strong>Scan pairing code</strong>.</li>
          <li>Press <strong>Pair your phone</strong> here and scan the code.</li>
        </ol>
      )
    }
  } else if (state === 'lapsed') {
    body = (
      <>
        <h3 className="cloud-hero-title">
          {plan.declined ? 'Your last Patreon payment didn’t go through' : 'Your membership ended'}
        </h3>
        <p className="cloud-hero-lede">
          {devices.length
            ? 'Your phone stays paired and keeps what it already has. '
            : ''}
          Renew to get syncing again; it picks up where it left off.
        </p>
        <div className="cloud-hero-actions">
          {button(plan.declined ? 'Fix it on Patreon' : `Renew on Patreon — $${PHONE_PRICE}/month`, openMembership)}
          {recheckLink('Renewed? Check again')}
        </div>
      </>
    )
    if (devices.length) {
      side = (
        <div>
          <h4 className="cloud-hero-subhead">Still paired</h4>
          <PhonePairing devices={devices} canPair={false} onRevoke={onRevoke} />
        </div>
      )
    }
  }

  return (
    <section className={`settings-section cloud-hero cloud-hero--${state} ${side ? 'has-side' : ''}`}
             aria-live="polite">
      <div className="cloud-hero-body">{body}</div>
      {side && <div className="cloud-hero-side">{side}</div>}
    </section>
  )
}
