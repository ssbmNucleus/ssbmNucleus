import { playSound, playHoverSound } from '../../shared/audio/sounds'

// These used to gate Watch Lite and the Watch buttons behind Patreon. Desktop
// Tracker is free now, so both components are what their unlocked branch
// always was: the app's chip/action buttons with its hover and click sounds.
//
// The file and export names are kept so the seven call sites don't churn. The
// two components differ in one deliberate way — LiteButton plays 'boop' for
// the caller, PremiumActionButton leaves the sound to the caller's onClick —
// which is how they behaved when unlocked, and callers depend on it.

/** Full-size ACTION button (Watch, Play the reel, …). Does NOT play a click
 * sound: the callers' own onClick handlers do. */
export function PremiumActionButton({ className = '', title, onClick,
                                      disabled = false, children }) {
  return (
    <button type="button" className={className} title={title} disabled={disabled}
            onMouseEnter={playHoverSound}
            onClick={onClick}>
      {children}
    </button>
  )
}

/** Drop-in for any Watch Lite trigger. Keeps the site's own chip class for
 * size/shape and plays the click sound before opening. */
export default function LiteButton({ className = '', title, onOpen, disabled = false, children }) {
  return (
    <button type="button" className={className} title={title} disabled={disabled}
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onOpen() }}>
      {children}
    </button>
  )
}
