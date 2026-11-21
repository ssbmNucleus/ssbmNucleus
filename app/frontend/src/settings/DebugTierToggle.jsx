import { useEffect, useState } from 'react'
import { getPremiumOverride, setPremiumOverride, DEBUG_PREMIUM_EVENT } from '../shared/account/usePremium'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import './DebugTierToggle.css'

// Dev-only header chip: cycles the effective tier real → premium → free so
// gated surfaces can be previewed without a Patreon pledge. Only rendered in
// DEV builds (App.jsx guards on import.meta.env.DEV; usePremium ignores the
// override key in production regardless).
export default function DebugTierToggle() {
  const [override, setOverride] = useState(getPremiumOverride)

  useEffect(() => {
    const sync = () => setOverride(getPremiumOverride())
    window.addEventListener(DEBUG_PREMIUM_EVENT, sync)
    return () => window.removeEventListener(DEBUG_PREMIUM_EVENT, sync)
  }, [])

  const cycle = () => {
    playSound('boop')
    const next = override == null ? true : override === true ? false : null
    setPremiumOverride(next)
    setOverride(next)
  }

  const label = override == null ? 'real' : override ? 'premium' : 'free'
  return (
    <button
      type="button"
      className={`debug-tier ${override == null ? '' : 'debug-tier--forced'}`}
      title="DEV only: force the app to treat you as premium/free (cycles real → premium → free)"
      onMouseEnter={playHoverSound}
      onClick={cycle}
    >
      tier·{label}
    </button>
  )
}
