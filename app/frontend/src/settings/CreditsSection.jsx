/**
 * CreditsSection - Settings entry point for the Credits modal.
 *
 * Deliberately thin: the content lives in CreditsModal so Settings stays a grid
 * of short cards.
 */
import { useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import CreditsModal from './CreditsModal'

export default function CreditsSection() {
  const [show, setShow] = useState(false)

  return (
    <section className="settings-section">
      <h3>Credits</h3>
      <p className="section-description">
        SSBM Nucleus is built on tools made by the Melee modding community.
      </p>
      <button
        className="credits-open-button"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('start'); setShow(true) }}
      >
        View credits
      </button>

      <CreditsModal show={show} onClose={() => setShow(false)} />
    </section>
  )
}
