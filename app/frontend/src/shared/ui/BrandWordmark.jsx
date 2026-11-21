import { playHoverSound } from '../audio/sounds'
import BrandLogo from './BrandLogo'
import './BrandWordmark.css'

// Shared header brand: hexagon logo + text wordmark + version. The ENTIRE
// block is the nucleus <-> stats mode toggle (loud control, not an easter
// egg). The wordmark always reads "SSBM Nucleus" — one brand — and stats
// mode announces itself with a superscript "stats" tag sliding in after the
// word while the glow and accent flood turn green. (An earlier design
// morphed the suffix into a separate "Nucleome" brand; that split the brand,
// so it's gone. The internal mode id is still 'nucleome'.)
export default function BrandWordmark({ mode, appVersion, onToggle }) {
  const isStats = mode === 'nucleome'

  // No onToggle = the stats mode is gated off (packaged builds without it).
  // Render the wordmark as inert branding: no button role, no hover sound,
  // and crucially no "Switch to Stats" tooltip advertising an absent mode.
  const interactive = typeof onToggle === 'function'

  return (
    <div
      className={`header-brand brand-toggle brand-toggle--${isStats ? 'nucleome' : 'nucleus'}${interactive ? '' : ' brand-toggle--static'}`}
      {...(interactive ? {
        role: 'button',
        tabIndex: 0,
        title: isStats ? 'Switch to Nucleus' : 'Switch to Tracker',
        'aria-label': isStats ? 'Switch to Nucleus mode' : 'Switch to Tracker mode',
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
          <span className="brand-stats-tag" aria-hidden={!isStats}>
            tracker
          </span>
        </span>
      </h1>
      {appVersion && (
        <span className="app-version" title={`SSBM Nucleus v${appVersion}`}>v{appVersion}</span>
      )}
    </div>
  )
}
