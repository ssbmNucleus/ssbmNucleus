/**
 * PhonePairing - pair a phone (a QR the phone scans) and the list of phones
 * already paired. Lives in the Cloud hero: for a paying user pairing is the
 * next thing to do, so it sits up front rather than at the bottom of a card.
 * The device list is the parent's (VaultSection), because whether a phone is
 * still paired also decides which hero a lapsed member sees.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { friendlyCloudError } from './cloudErrors'
import { pairedPhoneState } from './cloudAccount'
import { relativeTime } from './relativeTime'

const API = `${BACKEND_URL}/api/nucleome`

// The pairing QR encodes a bearer token for the whole replay library, and this
// app gets streamed and screenshotted. It self-destructs so a forgotten window
// can't keep handing out library access.
const QR_TTL_MS = 2 * 60 * 1000

/** Dark-on-light no matter the app theme — phone cameras need the real
 * contrast, and our surface tokens are far too dark to scan. */
function QrCode({ value, size = 176 }) {
  const [path, setPath] = useState({ d: '', count: 0 })

  useEffect(() => {
    let cancelled = false
    setPath({ d: '', count: 0 })
    import('qrcode-generator').then(({ default: qrcode }) => {
      if (cancelled) return
      const qr = qrcode(0, 'M') // 0 = pick the smallest type number that fits
      qr.addData(value)
      qr.make()
      const count = qr.getModuleCount()
      let d = ''
      for (let row = 0; row < count; row += 1) {
        for (let col = 0; col < count; col += 1) {
          if (qr.isDark(row, col)) d += `M${col} ${row}h1v1h-1z`
        }
      }
      setPath({ d, count })
    }).catch(() => {})
    return () => { cancelled = true }
  }, [value])

  // 4 modules of quiet zone on every side, or scanners won't find the symbol.
  const span = path.count + 8
  return (
    <svg
      className="vault-qr"
      width={size}
      height={size}
      viewBox={`-4 -4 ${span} ${span}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label="Pairing QR code"
    >
      <rect x="-4" y="-4" width={span} height={span} fill="#ffffff" />
      <path d={path.d} fill="#000000" />
    </svg>
  )
}

function DeviceRow({ device, onRevoke }) {
  const [confirming, setConfirming] = useState(false)

  // A primed "Really revoke?" that survives indefinitely is a mis-click waiting
  // to happen, so the confirm state expires on its own.
  useEffect(() => {
    if (!confirming) return undefined
    const id = setTimeout(() => setConfirming(false), 5000)
    return () => clearTimeout(id)
  }, [confirming])

  return (
    <li className="vault-device">
      <span className="vault-device-copy">
        <span className="vault-device-label">{device.label || 'Unnamed device'}</span>
        <span className="vault-device-seen">
          {device.is_self ? 'this computer — in use' : `last seen ${relativeTime(device.last_seen_at)}`}
        </span>
      </span>
      {/* No revoke on the device you are sitting at. Only a desktop can pair
          or revoke, so revoking this one destroys the credential you would
          need to undo it — the server refuses it too, but a button that only
          ever produces an error should not be there in the first place. */}
      {!device.is_self && (
        <button
          className="iso-browse-button danger"
          onMouseEnter={playHoverSound}
          onClick={() => {
            playSound('boop')
            if (confirming) { setConfirming(false); onRevoke(device.id) } else setConfirming(true)
          }}
        >
          {confirming ? 'Really revoke?' : 'Revoke'}
        </button>
      )}
    </li>
  )
}

export default function PhonePairing({ devices, canPair, onPaired, onRevoke }) {
  const [pairing, setPairing] = useState(null)
  const [pairLabel, setPairLabel] = useState('')
  const [showLink, setShowLink] = useState(false)
  const [copied, setCopied] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Whether the phone this code paired has shown up in the list yet.
  const pairedSeen = useRef(false)

  const hidePairing = useCallback(() => {
    pairedSeen.current = false
    setPairing(null)
    setShowLink(false)
    setCopied(false)
  }, [])

  // The token only ever lives in this state — leaving Settings unmounts the
  // section and takes the QR with it; this timer covers the case where the
  // user just walks away from an open Settings tab.
  useEffect(() => {
    if (!pairing) return undefined
    const expiresAt = Date.now() + QR_TTL_MS
    setSecondsLeft(Math.round(QR_TTL_MS / 1000))
    const id = setInterval(() => {
      const left = Math.round((expiresAt - Date.now()) / 1000)
      if (left <= 0) hidePairing()
      else setSecondsLeft(left)
    }, 1000)
    return () => clearInterval(id)
  }, [pairing, hidePairing])

  // A lapsed pledge takes the QR away with it.
  useEffect(() => { if (!canPair) hidePairing() }, [canPair, hidePairing])

  // So does revoking the phone it paired: its code no longer works (F-E-11).
  useEffect(() => {
    if (!pairing) return
    const state = pairedPhoneState(pairing.device_id, devices, pairedSeen.current)
    if (state === 'listed') pairedSeen.current = true
    else if (state === 'revoked') hidePairing()
  }, [pairing, devices, hidePairing])

  const startPair = async () => {
    playSound('start')
    setError('')
    setBusy(true)
    try {
      const data = await api.request(`${API}/vault/pair`, {
        method: 'POST',
        body: { label: pairLabel.trim() || 'Phone' },
      })
      pairedSeen.current = false
      setPairing(data)
      setShowLink(false)
      setCopied(false)
      setPairLabel('')
      onPaired?.()
    } catch (e) {
      setError(friendlyCloudError(e.message, e.status))
    } finally {
      setBusy(false)
    }
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(pairing.pair_url)
      setCopied(true)
    } catch { /* clipboard blocked — the link is on screen to type */ }
  }

  return (
    <div className="cloud-pairing">
      {devices.length > 0 && (
        <ul className="vault-devices">
          {devices.map((device) => (
            <DeviceRow key={device.id} device={device} onRevoke={onRevoke} />
          ))}
        </ul>
      )}

      {canPair && !pairing && (
        <div className="vault-pair-row">
          <input
            className="vault-input"
            type="text"
            value={pairLabel}
            placeholder="Phone name (e.g. Pixel)"
            aria-label="Phone name"
            disabled={busy}
            onChange={(e) => setPairLabel(e.target.value)}
          />
          <button
            className="iso-browse-button cloud-pair-button"
            disabled={busy}
            onMouseEnter={playHoverSound}
            onClick={startPair}
          >
            {busy ? 'Pairing…' : devices.length ? 'Pair another phone' : 'Pair your phone'}
          </button>
        </div>
      )}

      {pairing && (
        <div className="vault-qr-panel">
          <div className="vault-qr-warning">
            Anyone who scans this can see your cloud library.
          </div>
          <QrCode value={pairing.pair_url} />
          <div className="vault-qr-meta">
            Pairing “{pairing.label}” · hides in {secondsLeft}s
          </div>
          <div className="vault-qr-actions">
            <button className="iso-browse-button" onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); hidePairing() }}>
              Hide
            </button>
            <button className="iso-browse-button" onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); setShowLink((v) => !v) }}>
              {showLink ? 'Hide link' : 'Show link'}
            </button>
          </div>
          {/* The token is minted once and never shown again, so someone
              without a working camera needs a way to read it off. */}
          {showLink && (
            <div className="vault-link">
              <code className="vault-link-text">{pairing.pair_url}</code>
              <button className="iso-browse-button" onMouseEnter={playHoverSound} onClick={copyLink}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}
        </div>
      )}

      {error && <div className="vault-error" role="alert">{error}</div>}
    </div>
  )
}
