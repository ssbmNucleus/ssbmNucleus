import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { playSound } from '../audio/sounds'
import { appAlert, appConfirm, appPrompt, setAppDialogHandler } from './appDialogs'
import './AppDialogHost.css'

export default function AppDialogHost() {
  const [queue, setQueue] = useState([])
  const [promptValue, setPromptValue] = useState('')
  const inputRef = useRef(null)
  const current = queue[0] || null

  useEffect(() => {
    const removeHandler = setAppDialogHandler((options) => new Promise((resolve) => {
      setQueue(prev => [...prev, { ...options, resolve }])
    }))

    const originalAlert = window.alert
    const originalConfirm = window.confirm
    const originalPrompt = window.prompt

    window.alert = (message) => {
      appAlert(message)
    }
    window.confirm = (message) => {
      appConfirm(message)
      return false
    }
    window.prompt = (message, defaultValue = '') => {
      appPrompt(message, { defaultValue })
      return null
    }

    return () => {
      removeHandler()
      window.alert = originalAlert
      window.confirm = originalConfirm
      window.prompt = originalPrompt
    }
  }, [])

  useEffect(() => {
    if (!current) return
    setPromptValue(current.defaultValue || '')
    if (current.type === 'prompt') {
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [current])

  // Escape always gets out of an alert or confirm (as Cancel), so a dialog can
  // never trap the user. Capture phase, so the modal underneath that raised
  // it does not also close. A prompt's input handles its own Escape.
  useEffect(() => {
    if (!current || current.type === 'prompt') return undefined
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopPropagation()
      playSound('back')
      current.resolve(current.type === 'confirm' ? false : undefined)
      setQueue(prev => prev.slice(1))
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [current])

  if (!current) return null

  const closeCurrent = (value) => {
    current.resolve(value)
    setQueue(prev => prev.slice(1))
  }

  const handleConfirm = () => {
    playSound('boop')
    if (current.type === 'confirm') closeCurrent(true)
    else if (current.type === 'prompt') closeCurrent(promptValue)
    else closeCurrent(undefined)
  }

  const handleCancel = () => {
    playSound('back')
    closeCurrent(current.type === 'confirm' ? false : current.type === 'prompt' ? null : undefined)
  }

  const content = (
    <div className="app-dialog-overlay" role="presentation">
      <div
        className={`app-dialog app-dialog-${current.type}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-dialog-title"
      >
        <h2 id="app-dialog-title">{current.title}</h2>
        <p className="app-dialog-message">{current.message}</p>

        {current.type === 'prompt' && (
          <input
            ref={inputRef}
            className="app-dialog-input"
            value={promptValue}
            placeholder={current.placeholder}
            onChange={(e) => setPromptValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConfirm()
              if (e.key === 'Escape') handleCancel()
            }}
          />
        )}

        <div className="app-dialog-buttons">
          {current.type !== 'alert' && (
            <button className="btn-cancel" onClick={handleCancel}>
              {current.cancelText || 'Cancel'}
            </button>
          )}
          <button
            className={current.confirmStyle === 'danger' ? 'btn-danger' : 'btn-save'}
            onClick={handleConfirm}
          >
            {current.confirmText || 'OK'}
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(content, document.body)
}
