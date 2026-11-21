/**
 * InGameTestPanel - inline "Test in game" button + progress/result panel.
 *
 * Used by the custom character / custom stage detail views (which aren't modals).
 * Pass a useInGameTest() instance as `test` and an `onStart` handler. Mirrors the
 * costume modal's overlay: prepare a session, play with port 1, then Stop.
 * Automated screenshot captures retain their separate result flow.
 */

import DolphinEmbedPanel from './DolphinEmbedPanel'
import { backendMediaUrl } from '../config/config'
import HexagonLoader from '../ui/HexagonLoader'
import './InGameTestPanel.css'

const VERDICT_LABEL = {
  healthy: 'PASS',
  ended: 'PASS — match ended',
  never_started: 'DID NOT START',
  hung: 'HUNG',
  crashed: 'CRASH',
  error: 'ERROR',
}

export function InGameTestRunning({ test, fill = false, previewActive = true, captureSessionId }) {
  const { testStatus, testMode, testError, stoppingTest, stopError, stopTest } = test
  const stage = testStatus?.stage
  const interactive = testMode === 'test'
  const playing = interactive && stage === 'playing'
  const waiting = ['waiting', 'waiting_controller', 'recovering'].includes(stage)
  const showEmbed = previewActive && !['starting', 'building', 'waiting', 'recovering'].includes(stage)
  const heading = playing ? 'Port 1 — play' : stage === 'building' ? 'Building…'
    : stage === 'waiting' ? 'Waiting for Dolphin' : interactive ? 'Preparing…' : 'Capturing…'
  const stopBtn = interactive && (
    <button type="button" className="btn-secondary ingame-stop" onClick={stopTest} disabled={stoppingTest}>
      {stoppingTest ? 'Stopping…' : 'Stop'}
    </button>
  )
  const errorLine = (stopError || testError) && (
    <p role="alert" className="ingame-error">{stopError || testError}</p>
  )

  if (showEmbed) {
    // Dolphin is up: one compact row, then the embed takes everything else
    return (
      <div className="ingame-running ingame-running--embed">
        <div className="ingame-row">
          <span className="ingame-heading">{heading}</span>
          {!playing && <span className="ingame-status" role="status">{testStatus?.message || ''}</span>}
          {stopBtn}
        </div>
        {errorLine}
        <DolphinEmbedPanel active fill={fill} expectedSessionId={captureSessionId} />
      </div>
    )
  }

  // Building / waiting: centred loader + one status line
  return (
    <div className="ingame-running">
      <HexagonLoader size={72}
        label={waiting ? 'Waiting' : interactive ? 'Preparing' : 'Capturing'}
        progress={waiting ? null : Number.isFinite(testStatus?.percentage) ? testStatus.percentage : null}
        centerLabel={waiting ? '…' : `${Math.round(testStatus?.percentage || 0)}%`}
        minimumVisibleProgress={4} />
      <h3 className="ingame-heading ingame-heading--big">{heading}</h3>
      <p role="status" className="ingame-status">{testStatus?.message || ''}</p>
      {stopBtn}
      {errorLine}
    </div>
  )
}

export default function InGameTestPanel({ test, onStart, label = 'Test in Game', disabled = false }) {
  const { testingInGame, testResult, testError, resetTest } = test

  if (testingInGame) {
    return <div style={{ textAlign: 'center', padding: '1rem' }}><InGameTestRunning test={test} /></div>
  }

  if (testError) {
    return (
      <div style={{ textAlign: 'center', padding: '1rem' }}>
        <p style={{ color: 'var(--color-error, #e74c3c)', marginBottom: '0.75rem' }}>{testError}</p>
        <button className="btn-secondary" onClick={resetTest}>Close</button>
      </div>
    )
  }

  if (testResult) {
    const r = testResult
    return (
      <div style={{ textAlign: 'center', padding: '1rem' }}>
        <div style={{
          display: 'inline-block', padding: '0.35rem 1.1rem', borderRadius: 'var(--radius-md)',
          fontWeight: 700, fontSize: '1.15em', marginBottom: '0.75rem', color: '#fff',
          background: r.success ? 'var(--color-success, #2ecc71)' : 'var(--color-error, #e74c3c)'
        }}>
          {r.interactive ? (r.success ? 'Session ended' : 'Session failed') : r.success ? '✓ PASS' : `✕ ${VERDICT_LABEL[r.verdict] || String(r.verdict || '').toUpperCase()}`}
        </div>
        <p style={{ color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>{r.reason}</p>
        {r.screenshot && (
          <img
            src={backendMediaUrl(r.screenshot)}
            alt="In-game screenshot"
            style={{ maxWidth: '100%', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)', marginBottom: '1rem' }}
          />
        )}
        {Array.isArray(r.checks) && r.checks.length > 0 && (
          <ul style={{ listStyle: 'none', padding: 0, textAlign: 'left', maxWidth: 480, margin: '0 auto 1rem' }}>
            {r.checks.map((c, i) => {
              const ok = c.verdict === 'healthy'
              return (
                <li key={i} style={{ padding: '0.4rem 0', borderBottom: '1px solid var(--color-border)' }}>
                  <span style={{ color: ok ? 'var(--color-success, #2ecc71)' : 'var(--color-error, #e74c3c)', marginRight: '0.5rem', fontWeight: 700 }}>
                    {ok ? '✓' : '✕'}
                  </span>
                  <span style={{ color: 'var(--color-text-primary)' }}>{c.label}</span>
                  {!ok && c.reason && (
                    <div style={{ fontSize: '0.8em', color: 'var(--color-text-secondary)', marginLeft: '1.5rem' }}>{c.reason}</div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
          <button className="btn-export" onClick={onStart} disabled={disabled}>Test again</button>
          <button className="btn-secondary" onClick={resetTest}>Close</button>
        </div>
      </div>
    )
  }

  return (
    <button
      className="btn-export"
      onClick={onStart}
      disabled={disabled}
      title="Build a one-mod test ISO and play it with your port 1 controller until you stop"
    >
      🎮 {label}
    </button>
  )
}
