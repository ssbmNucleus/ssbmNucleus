import { playHoverSound } from '../audio/sounds'
import { PLAY_ENABLED } from '../config/features'
import BrandLogo from './BrandLogo'
import { MODE_NAMES } from './modeCycle'
import './BrandWordmark.css'

// Shared header brand: hexagon logo + text wordmark + version. The ENTIRE
// block is the mode switch (loud control, not an easter egg): each click goes
// to the next mode of the cycle in modeCycle.js, Nucleus -> Tracker -> Play.
// The wordmark always reads "SSBM Nucleus" — one brand — and the other modes
// announce themselves with a superscript tag sliding in after the word:
// "tracker" as the glow and accent flood turn green, "unlocked" (the mode whose id is
// 'play') as they turn purple, so the wordmark reads "SSBM Nucleus Unlocked".
// (An earlier design morphed the suffix into a separate "Nucleome" brand; that
// split the brand, so it's gone. The internal Tracker mode id is still
// 'nucleome'.) `nextMode` is where a click goes; the tooltip says so.
export default function BrandWordmark({ mode, appVersion, onToggle, nextMode = 'nucleus' }) {
  const look = mode === 'nucleome' || mode === 'play' ? mode : 'nucleus'
  const nextName = MODE_NAMES[nextMode] || MODE_NAMES.nucleus

  // No onToggle = this build has no other mode to go to (packaged builds
  // without Tracker or Play). Render the wordmark as inert branding: no button
  // role, no hover sound, and no "Switch to ..." tooltip advertising an absent mode.
  const interactive = typeof onToggle === 'function'

  return (
    <div
      className={`header-brand brand-toggle brand-toggle--${look}${interactive ? '' : ' brand-toggle--static'}`}
      {...(interactive ? {
        role: 'button',
        tabIndex: 0,
        title: `Switch to ${nextName}`,
        'aria-label': `Switch to ${nextName} mode`,
        onMouseEnter: playHoverSound,
        onClick: onToggle,
        onKeyDown: (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onToggle()
          }
        },
      } : {})}
    >
      <BrandLogo />
      <h1>
        <span className="brand-ssbm">SSBM</span>{' '}
        <span className="brand-word">
          <span className="vault-text">Nucle</span>
          <span className="brand-suffix">us</span>
          <span className="brand-mode-tag brand-stats-tag" aria-hidden={look !== 'nucleome'}>
            tracker
          </span>
          {PLAY_ENABLED && (
            <span className="brand-mode-tag brand-play-tag" aria-hidden={look !== 'play'}>
              unlocked
            </span>
          )}
        </span>
      </h1>
      {appVersion && (
        <span className="app-version" title={`SSBM Nucleus v${appVersion}`}>v{appVersion}</span>
      )}
    </div>
  )
}
