// scan — in-app camera scanner for the pairing QR.
//
// The QR encodes this site's URL with #t=<device token>, which works when the
// phone's camera app scans it — but someone already ON the auth page (opened
// the link by hand, or just unpaired) was stuck retyping the token. This
// overlay reads the same QR with the page's own camera.
//
// Decoding is two-tier: the native BarcodeDetector where it exists (Android
// Chrome — hardware-fast, zero bundle cost), else the vendored jsQR run over
// downscaled canvas frames (iOS Safari has no BarcodeDetector as of 2026).
// Both paths accept either the full pairing URL or a bare token, so a token
// QR'd by anything else (a password manager, a chat app) still pairs.
import jsQR from './vendor/jsqr.js'
import { el, toast } from './ui'

/** The token inside a scanned string: a pairing URL's fragment, or the string
 * itself if it already looks like a token. Mirrors main.js claimTokenFromUrl
 * and the backend's nvt_<24 url-safe bytes> shape. */
export function tokenFromScan(text) {
  const s = String(text || '').trim()
  const m = /[#&?]t=([A-Za-z0-9_-]{16,})/.exec(s)
  if (m) return m[1]
  return /^[A-Za-z0-9_-]{16,}$/.test(s) ? s : null
}

/** Open the fullscreen scanner. Calls onToken(token) and closes on a hit.
 * Closes silently on cancel; toasts and closes if the camera is unavailable
 * (denied, no device, insecure context) — the paste field is the fallback. */
export async function openScanner(onToken) {
  if (!navigator.mediaDevices?.getUserMedia) {
    toast('This browser has no camera access — paste the token instead.')
    return
  }

  const overlay = el(`<div class="scanner">
    <video class="scanner-video" playsinline muted autoplay></video>
    <div class="scanner-chrome">
      <div class="scanner-frame"></div>
      <p class="scanner-hint">Point at the pairing code in Nucleus settings</p>
      <button class="scanner-cancel">Cancel</button>
    </div>
  </div>`)
  const video = overlay.querySelector('video')
  const hint = overlay.querySelector('.scanner-hint')

  let stream = null
  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    stream?.getTracks().forEach((t) => t.stop())
    overlay.remove()
    document.body.classList.remove('no-scroll')
  }
  overlay.querySelector('.scanner-cancel').addEventListener('click', close)

  document.body.appendChild(overlay)
  document.body.classList.add('no-scroll')

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
    })
  } catch {
    close()
    toast('Camera unavailable — allow camera access, or paste the token instead.')
    return
  }
  if (closed) { stream.getTracks().forEach((t) => t.stop()); return }
  video.srcObject = stream
  video.play().catch(() => { /* iOS resolves play() late; autoplay covers it */ })

  // Native detector when constructible — construction itself can throw on
  // browsers that expose the class but not qr_code.
  let detector = null
  if ('BarcodeDetector' in window) {
    try { detector = new window.BarcodeDetector({ formats: ['qr_code'] }) } catch { /* jsQR path */ }
  }
  // jsQR frames are decoded at reduced width: decode cost scales with pixels
  // and a QR that fills a phone viewfinder is comfortably readable at 640.
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d', { willReadFrequently: true })

  let lastMiss = 0
  const found = (raw) => {
    const token = tokenFromScan(raw)
    if (token) {
      close()
      onToken(token)
      return true
    }
    // a QR, but not ours — say so once in a while rather than sitting silent
    if (Date.now() - lastMiss > 3000) {
      lastMiss = Date.now()
      hint.textContent = "That's a QR code, but not a Nucleus pairing code"
    }
    return false
  }

  const tick = async () => {
    if (closed) return
    if (video.readyState >= 2) {
      if (detector) {
        try {
          const codes = await detector.detect(video)
          if (codes.length && found(codes[0].rawValue)) return
        } catch { detector = null /* detect() unsupported after all */ }
      } else {
        const w = Math.min(640, video.videoWidth || 640)
        const h = Math.round(w * (video.videoHeight || 480) / (video.videoWidth || 640))
        if (w && h) {
          canvas.width = w
          canvas.height = h
          ctx.drawImage(video, 0, 0, w, h)
          const img = ctx.getImageData(0, 0, w, h)
          const hit = jsQR(img.data, w, h, { inversionAttempts: 'dontInvert' })
          if (hit?.data && found(hit.data)) return
        }
      }
    }
    setTimeout(tick, 200)
  }
  tick()
}
