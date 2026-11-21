/**
 * BugReportSection - Settings entry point for the Bug Report modal.
 *
 * Deliberately thin (the CreditsSection pattern): the form lives in
 * BugReportModal so Settings stays a grid of short cards.
 */
import { useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import BugReportModal from './BugReportModal'

export default function BugReportSection() {
  const [show, setShow] = useState(false)

  return (
    <section className="settings-section">
      <h3>Bug Report</h3>
      <button
        className="credits-open-button bugreport-open-button"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('start'); setShow(true) }}
      >
        Report a Bug
      </button>

      <BugReportModal show={show} onClose={() => setShow(false)} />
    </section>
  )
}
