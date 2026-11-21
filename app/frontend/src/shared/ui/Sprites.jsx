import { useEffect, useRef, useState } from 'react'
import { BACKEND_URL } from '../config/config'
import { api } from '../transport/api'

const SPRITES = `${BACKEND_URL}/api/nucleome/sprites`

// Module-level manifest cache: one fetch per app session.
let manifestPromise = null
function getManifest() {
  if (!manifestPromise) {
    manifestPromise = api.get('/api/nucleome/sprites').catch(() => null)
  }
  return manifestPromise
}

const spriteUrl = (name) => `${SPRITES}/${name}`

// Randall, ripped from the vanilla ISO by sprites.py — three face frames and
// a 1200-frame (20s @ 60fps) blink timeline: [[frame_time, face_index], ...].
export function Randall({ size = 48, className = '', speed = 0.35, animated = true }) {
  const [manifest, setManifest] = useState(null)
  const [face, setFace] = useState(0)
  const rafRef = useRef(null)

  useEffect(() => { getManifest().then(setManifest) }, [])

  useEffect(() => {
    if (!manifest?.randall || !animated) return undefined
    const { frames, blink_track: track, blink_loop_frames: loop } = manifest.randall
    frames.forEach((f) => { new Image().src = spriteUrl(f) })
    const start = performance.now()
    const tick = (now) => {
      // `speed` < 1 slows the whole blink timeline down (1 = authentic timing)
      const frame = ((now - start) / 1000) * 60 * speed % loop
      let idx = 0
      for (const [t, faceIdx] of track) {
        if (t <= frame) idx = faceIdx
        else break
      }
      setFace(idx)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [manifest, animated])

  if (!manifest?.randall) return null
  return (
    <img
      className={`sprite-pixel ${className}`}
      src={spriteUrl(manifest.randall.frames[face] || manifest.randall.frames[0])}
      alt=""
      width={size}
      height={size}
      aria-hidden="true"
    />
  )
}
