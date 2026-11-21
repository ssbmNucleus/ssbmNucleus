/** CreditsModal - the people and projects Nucleus is built on. */
import { useEffect } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import '../shared/ui/CreditsModalChrome.css'
import './CreditsModal.css'

// Deliberately credits the two authors whose work Nucleus leans on hardest, plus
// the PROJECTS rather than every individual contributor. Smaller contributors are
// not named: being listed in a shipped desktop app is more public than someone who
// sent a couple of commits necessarily asked for. The repo links below lead to the
// full contributor lists for anyone who wants them.
const PEOPLE = [
  {
    name: 'Ploaj',
    url: 'https://github.com/Ploaj',
    work: 'HSDLib / HSDRaw / HSDRawViewer · MexManager · MeleeMedia · IONET',
  },
  {
    name: 'UnclePunch',
    url: 'https://github.com/UnclePunch',
    work: 'Dynamic Alternate Stages',
  },
  {
    name: 'Team Akaneia',
    url: 'https://github.com/akaneia/m-ex',
    work: 'm-ex project',
  },
  {
    name: 'Project Slippi',
    url: 'https://slippi.gg',
    work: 'Slippi · playback Dolphin · slippi-js',
  },
  {
    name: 'slippilab',
    url: 'https://github.com/frankborden/slippilab',
    work: 'Character animation data',
  },
  {
    name: 'peppi',
    url: 'https://github.com/hohav/peppi',
    work: '.slp replay parsing',
  },
  {
    name: 'Dolphin Emulator',
    url: 'https://dolphin-emu.org',
    work: 'GameCube emulation',
  },
  {
    name: 'Wiimm',
    url: 'https://wit.wiimm.de/',
    work: 'Wiimms ISO Tools (wit)',
  },
  {
    name: 'Changing Color Effects in Melee',
    url: 'https://smashboards.com/threads/changing-color-effects-in-melee.313177/',
    work: 'Effect color offsets',
  },
]

export default function CreditsModal({ show, onClose }) {
  // Close on Escape, matching the other overlays in the app.
  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => { if (e.key === 'Escape') { playSound('back'); onClose() } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [show, onClose])

  if (!show) return null

  const openLink = (url) => {
    playSound('click')
    if (window.electron) window.electron.openExternal(url)
    else window.open(url, '_blank')
  }

  return (
    <div className="credits-overlay" onClick={() => { playSound('back'); onClose() }}>
      <div className="credits-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="credits-modal-title">Credits</h2>
        <p className="credits-modal-sub">
          SSBM Nucleus is built on tools made by the Melee modding community.
          It would not exist without them.
        </p>

        <div className="credits-body">
          <div className="credits-author">
            <span className="credits-author-label">SSBM Nucleus by</span>
            <span className="credits-author-name">sc00p</span>
          </div>
          <ul className="credits-list">
            {PEOPLE.map((p) => (
              <li key={p.name} className="credits-entry">
                <button
                  className="credits-name"
                  onMouseEnter={playHoverSound}
                  onClick={() => openLink(p.url)}
                >
                  {p.name}
                </button>
                <span className="credits-work">{p.work}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="credits-modal-buttons">
          <button
            className="credits-close-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('back'); onClose() }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
