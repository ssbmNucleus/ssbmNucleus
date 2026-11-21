/**
 * Melee Menu Sound Effects
 * Preloads and plays menu sounds from vanilla Melee assets
 */
import { BACKEND_URL } from '../config/config'

// Default volume (0.0 to 1.0)
const DEFAULT_VOLUME = 0.3

// Load saved volume from localStorage, or use default
let masterVolume = (() => {
  const saved = localStorage.getItem('settings_master_volume')
  return saved !== null ? parseFloat(saved) : DEFAULT_VOLUME
})()

// Sound file names mapping
const SOUND_FILES = {
  back: 'back.wav',
  start: 'start.wav',
  tick: 'tick.wav',
  boop: 'click.wav',
  error: 'error.wav',
  camera: 'camera_click.wav',
  newSkin: 'new_skin.wav',
  achievement: 'big_achievement.wav',
}

// Audio instances (created lazily or on reload)
let sounds = {}

// Create audio instances for all sounds
const createSounds = () => {
  sounds = {}
  Object.entries(SOUND_FILES).forEach(([name, file]) => {
    sounds[name] = new Audio(`${BACKEND_URL}/vanilla/sounds/${file}`)
  })
}

// Apply volume to all sounds (achievement is quieter)
const applyVolume = () => {
  Object.entries(sounds).forEach(([name, sound]) => {
    sound.volume = name === 'achievement' ? masterVolume * 0.66 : masterVolume
  })
}

// Initialize sounds
createSounds()
Object.values(sounds).forEach(s => s.load())
applyVolume()

// Hover debounce - prevent tick spam on rapid hovers
let lastHoverTime = 0
const HOVER_DEBOUNCE_MS = 50

/**
 * Play a menu sound effect
 * @param {'back'|'start'|'tick'|'error'|'camera'|'newSkin'} name - Sound name to play
 */
export const playSound = (name) => {
  const sound = sounds[name]
  if (sound) {
    sound.currentTime = 0
    sound.play().catch(() => {}) // Ignore autoplay restrictions
  }
}

/**
 * Play tick sound on hover (debounced to prevent spam)
 */
export const playHoverSound = () => {
  const now = Date.now()
  if (now - lastHoverTime > HOVER_DEBOUNCE_MS) {
    lastHoverTime = now
    playSound('tick')
  }
}

/**
 * Get the current master volume (0.0 to 1.0)
 */
export const getMasterVolume = () => masterVolume

/**
 * Set the master volume and persist to localStorage
 * @param {number} volume - Volume level from 0.0 to 1.0
 */
export const setMasterVolume = (volume) => {
  masterVolume = Math.max(0, Math.min(1, volume))
  localStorage.setItem('settings_master_volume', masterVolume.toString())
  applyVolume()
}

/**
 * Reload all sounds (call after first-run setup extracts sounds)
 * Creates fresh Audio instances and preloads them
 */
export const reloadSounds = () => {
  createSounds()
  Object.values(sounds).forEach(s => s.load())
  applyVolume()
}
