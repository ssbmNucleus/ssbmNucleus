/**
 * VolumeSection - Master volume control for menu sounds
 */
import { useState } from 'react'
import { playSound, getMasterVolume, setMasterVolume } from '../shared/audio/sounds'

export default function VolumeSection() {
  const [volume, setVolume] = useState(getMasterVolume())

  const handleVolumeChange = (e) => {
    const newVolume = parseFloat(e.target.value)
    setVolume(newVolume)
    setMasterVolume(newVolume)
  }

  const handleSliderRelease = () => {
    // Play a preview sound when user releases the slider
    if (volume > 0) {
      playSound('boop')
    }
  }

  const volumePercent = Math.round(volume * 100)

  return (
    <section className="settings-section">
      <h3>Sound</h3>
      <p className="section-description">
        Adjust the volume of menu sound effects.
      </p>
      <div className="volume-control">
        <div className="volume-slider-container">
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={volume}
            onChange={handleVolumeChange}
            onMouseUp={handleSliderRelease}
            onTouchEnd={handleSliderRelease}
            className="volume-slider"
            style={{
              background: `linear-gradient(to right, #7dd3e8 0%, #7dd3e8 ${volumePercent}%, #2a2a3e ${volumePercent}%, #2a2a3e 100%)`
            }}
          />
          <span className="volume-value">{volumePercent}%</span>
        </div>
      </div>
    </section>
  )
}
