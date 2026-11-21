import { useState, useEffect, useRef } from 'react'
import { API_URL } from '../../shared/config/config.js'

/**
 * Victory-theme / announcer-call preview for one custom character.
 *
 * Only one clip plays at a time: clicking the kind that is already playing
 * stops it, clicking the other kind swaps to it, and whatever is playing is
 * stopped when the page unmounts.
 */
export function useCharacterAudio(slug) {
  const [playingAudio, setPlayingAudio] = useState(null)        // 'victory' | 'announcer'
  const audioRef = useRef(null)

  // stop audio when leaving the page
  useEffect(() => () => { audioRef.current?.pause() }, [])

  const toggleAudio = (kind) => {
    if (playingAudio === kind) {
      audioRef.current?.pause()
      audioRef.current = null
      setPlayingAudio(null)
      return
    }
    audioRef.current?.pause()
    const path = kind === 'victory' ? 'victory-theme' : 'announcer'
    const audio = new Audio(`${API_URL}/custom-characters/${slug}/audio/${path}`)
    audio.onended = () => setPlayingAudio(null)
    audio.onerror = () => setPlayingAudio(null)
    audioRef.current = audio
    audio.play().catch(() => setPlayingAudio(null))
    setPlayingAudio(kind)
  }

  return { playingAudio, toggleAudio }
}
