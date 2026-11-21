/**
 * IsoPathSection - Vanilla ISO path management
 *
 * Features:
 * - Browse for vanilla Melee ISO
 * - Verify ISO against MD5 hash
 * - Display verification status
 * - Persist path to localStorage
 */
import { useState, useEffect, useRef } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'
import {
  classifyIsoVerification, classifyIsoVerificationFailure, createIsoVerificationGate,
} from './isoVerification'

export default function IsoPathSection({}) {
  const [vanillaIsoPath, setVanillaIsoPath] = useState('')
  const [isoMessage, setIsoMessage] = useState({ text: '', type: '' })
  const [isoVerified, setIsoVerified] = useState(null) // null = not checked, true = valid, false = invalid
  const [verifyingIso, setVerifyingIso] = useState(false)
  const [verificationUnavailable, setVerificationUnavailable] = useState(false)
  const verificationGate = useRef(createIsoVerificationGate())
  const currentPath = useRef('')

  // Load vanilla ISO path from localStorage on mount and verify it
  useEffect(() => {
    const savedPath = localStorage.getItem('vanilla_iso_path')
    if (savedPath) {
      setVanillaIsoPath(savedPath)
      // Verify on load
      verifyIso(savedPath)
    }
    return () => verificationGate.current.invalidate()
  }, [])

  const verifyIso = async (isoPath, { persistOnValid = false, clearInvalid = false } = {}) => {
    const request = verificationGate.current.begin(isoPath)
    currentPath.current = isoPath
    setVerifyingIso(true)
    setIsoVerified(null)
    setVerificationUnavailable(false)

    try {
      const data = await api.post('/verify-iso', { isoPath })
      if (!verificationGate.current.isCurrent(request, currentPath.current)) return
      const result = classifyIsoVerification(data)
      if (result.status === 'valid') {
        if (persistOnValid) localStorage.setItem('vanilla_iso_path', isoPath)
        setIsoVerified(true)
        setIsoMessage({ text: result.message, type: 'success' })
      } else {
        setIsoVerified(false)
        setIsoMessage({ text: result.message, type: 'error' })
        if (clearInvalid) {
          setVanillaIsoPath('')
        }
      }
    } catch (err) {
      if (!verificationGate.current.isCurrent(request, currentPath.current)) return
      const result = classifyIsoVerificationFailure(err)
      setIsoVerified(null)
      setVerificationUnavailable(true)
      setIsoMessage({ text: result.message, type: 'warning' })
    } finally {
      if (verificationGate.current.isCurrent(request, currentPath.current)) {
        setVerifyingIso(false)
      }
    }
  }

  const handleBrowseIso = async () => {
    if (!window.electron) {
      setIsoMessage({ text: 'Electron API not available', type: 'error' })
      return
    }

    try {
      const isoPath = await window.electron.openIsoDialog()
      if (isoPath) {
        verificationGate.current.invalidate()
        currentPath.current = isoPath
        setVanillaIsoPath(isoPath)
        setIsoVerified(null)
        setVerificationUnavailable(false)
        setIsoMessage({ text: 'Verifying ISO...', type: '' })
        await verifyIso(isoPath, { persistOnValid: true, clearInvalid: true })
      }
    } catch (err) {
      const result = classifyIsoVerificationFailure(err)
      setVerificationUnavailable(true)
      setIsoMessage({ text: result.message, type: 'warning' })
    }
  }

  const handleClearIsoPath = () => {
    localStorage.removeItem('vanilla_iso_path')
    verificationGate.current.invalidate()
    currentPath.current = ''
    setVanillaIsoPath('')
    setIsoVerified(null)
    setVerifyingIso(false)
    setVerificationUnavailable(false)
    setIsoMessage({ text: 'Vanilla ISO path cleared', type: 'success' })
  }

  return (
    <section className="settings-section">
      <h3>Vanilla ISO</h3>
      <p className="section-description">
        Set the path to your vanilla Melee ISO. This is required for applying xdelta patches.
      </p>

      <div className="iso-path-container">
        {vanillaIsoPath ? (
          <div className={`iso-path-display ${isoVerified === true ? 'verified' : isoVerified === false ? 'invalid' : ''}`}>
            <span className="iso-status-icon">
              {verifyingIso ? '...' : isoVerified === true ? '✓' : isoVerified === false ? '✕' : '?'}
            </span>
            <span className="iso-path-text" title={vanillaIsoPath}>{vanillaIsoPath}</span>
            <button
              className="iso-clear-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); handleClearIsoPath(); }}
              title="Clear ISO path"
            >
              ×
            </button>
          </div>
        ) : (
          <div className="iso-path-empty">No ISO path set</div>
        )}
        <button
          className="iso-browse-button"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); handleBrowseIso(); }}
          disabled={verifyingIso}
        >
          {verifyingIso ? 'Verifying...' : vanillaIsoPath ? 'Change' : 'Browse'}
        </button>
      </div>

      {isoMessage.text && (
        <div className={`message ${isoMessage.type}`}>
          {isoMessage.text}
          {verificationUnavailable && vanillaIsoPath && (
            <button
              className="iso-browse-button"
              onClick={() => verifyIso(vanillaIsoPath, { persistOnValid: true, clearInvalid: true })}
              disabled={verifyingIso}
            >
              Retry verification
            </button>
          )}
        </div>
      )}
    </section>
  )
}
