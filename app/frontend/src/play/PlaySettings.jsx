/**
 * PlaySettings - Play's own settings: the Nucleus game client Play installs and updates from the
 * signed client feed (play/managed.py), the game's own settings window, and, for developers, a
 * client folder of their own (verified by the backend before anything in it runs), which every
 * game starts from instead while it is set.
 */
import { useState } from 'react'
import { api } from '../shared/transport/api'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { APP_TOO_OLD, CPU_MESSAGE, gameSettingsNote, installJob, percent } from './playCards'

// The backend sends check times as epoch seconds and install times as ISO 8601 text.
function when(value) {
  if (!value) return null
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

function size(bytes) {
  return Number.isFinite(bytes) && bytes > 0 ? `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB` : null
}

/** The installed client: its version, updates, and the install or update running now. */
function ClientCard({ env, client: actions }) {
  const managed = env.managed || {}
  const client = env.client || {}
  const job = installJob(env)
  const installed = managed.installed
  const offer = managed.available
  const ownFolder = client.source === 'folder'
  const pct = job ? percent(job.progress) : 0

  return (
    <div className="play-settings-card">
      <h2>Nucleus Unlocked</h2>
      <p className="play-settings-help">
        The game every card starts. SSBM Nucleus installs it for you and keeps it up to date; your saves, settings and Melee disc are never touched.
      </p>
      {ownFolder && (
        <p className="play-settings-help">
          Your own client folder (below) is used instead while it is set.
        </p>
      )}
      {installed && (
        <dl className="play-client-facts">
          <dt>Version</dt><dd>{installed.version}</dd>
          {when(installed.installedAt) && <><dt>Installed</dt><dd>{when(installed.installedAt)}</dd></>}
          {!ownFolder && client.valid && client.cpuBaseline && <><dt>Needs</dt><dd>A processor with {client.cpuBaseline}</dd></>}
          {!ownFolder && client.valid && (
            <><dt>Replays</dt><dd>{client.playback ? 'Can be watched from Tracker' : 'Not in this version'}</dd></>
          )}
        </dl>
      )}
      {!ownFolder && client.valid && client.cpuSupported === false && <p className="play-message play-message--error">{CPU_MESSAGE}</p>}
      {managed.pending && (
        <p className="play-message play-message--success">
          Nucleus Unlocked {managed.pending.version} is ready. It is used from the next game you start once this one closes.
        </p>
      )}
      {job && (
        <>
          <p className="play-settings-help">
            {job.action === 'update' ? 'Updating' : 'Installing'} {pct ? `${pct}%` : '...'}{job.detail ? `: ${job.detail}` : ''}
          </p>
          <div className="play-progress play-progress--wide" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="play-progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </>
      )}
      {!job && managed.error && <p className="play-message play-message--error" role="alert">{managed.error}</p>}
      {!job && offer?.appTooOld && <p className="play-message play-message--error">{APP_TOO_OLD(offer)}</p>}
      {!job && installed && managed.updateAvailable && !offer?.appTooOld && (
        <p className="play-settings-help">
          Nucleus Unlocked {offer.version} is available{size(offer.size) ? ` (${size(offer.size)})` : ''}. You can keep playing while it downloads.
        </p>
      )}
      {!job && installed && !managed.updateAvailable && managed.checkedAt && !managed.checkError && (
        <p className="play-settings-help">Up to date (checked {when(managed.checkedAt)}).</p>
      )}
      {managed.checkError && !job && <p className="play-settings-help">{managed.checkError}</p>}
      <div className="play-settings-actions">
        {job && (
          <button type="button" className="play-secondary" onMouseEnter={playHoverSound} onClick={actions.cancel}>Cancel</button>
        )}
        {!job && !installed && (
          <button type="button" className="btn-primary play-button" disabled={!!offer?.appTooOld}
            onMouseEnter={playHoverSound} onClick={actions.install}>
            {managed.error ? 'Try again' : 'Install'}
          </button>
        )}
        {!job && installed && managed.updateAvailable && !offer?.appTooOld && (
          <button type="button" className="play-secondary" onMouseEnter={playHoverSound} onClick={actions.update}>
            Update to {offer.version}
          </button>
        )}
        {!job && installed && (
          <button type="button" className="play-secondary play-secondary--quiet" disabled={actions.checking}
            onMouseEnter={playHoverSound} onClick={() => actions.check(true)}>
            {actions.checking ? 'Checking...' : 'Check for updates'}
          </button>
        )}
      </div>
      {actions.error && <p className="play-message play-message--error" role="alert">{actions.error}</p>}
      {managed.testFeed && (
        <p className="play-settings-help">Development: this backend reads a local test feed, signed with a test key.</p>
      )}
    </div>
  )
}

/** For developers: a client folder of their own, which every game starts from while it is set. */
function OwnFolderCard({ env, onChanged }) {
  const [message, setMessage] = useState(null)
  const [saving, setSaving] = useState(false)
  const client = env.client || {}
  const own = client.source === 'folder'

  const save = async (folder) => {
    setSaving(true)
    setMessage(null)
    try {
      const data = await api.post('/api/play/client', { folder })
      playSound('boop')
      setMessage(folder ? { kind: 'success', text: data.client?.version ? `Client ${data.client.version} found.` : 'Client found.' } : null)
    } catch (err) {
      playSound('back')
      setMessage({ kind: 'error', text: err.message })
    } finally {
      setSaving(false)
      onChanged()
    }
  }

  const choose = async () => {
    if (!window.electron?.selectDirectory) {
      setMessage({ kind: 'error', text: 'Choosing a folder needs the Nucleus app.' })
      return
    }
    const folder = await window.electron.selectDirectory()
    if (folder) save(folder)
  }

  const engines = client.engines || {}
  return (
    <div className="play-settings-card">
      <h2>Your own client folder</h2>
      <p className="play-settings-help">
        For developers: a client you built yourself (the folder holding melee_source.exe). While it is set, every game starts from it instead of the installed Nucleus Unlocked.
      </p>
      <div className={`play-folder ${own ? (client.valid ? 'play-folder--ok' : 'play-folder--bad') : ''}`}>
        <span className="play-folder-path" title={own ? client.folder || '' : ''}>{own ? client.folder : 'Not set: games use the installed Nucleus Unlocked'}</span>
        <button type="button" className="play-secondary" disabled={saving} onMouseEnter={playHoverSound} onClick={choose}>
          {own ? 'Change' : 'Choose folder'}
        </button>
        {own && (
          <button type="button" className="play-secondary play-secondary--quiet" disabled={saving}
            onMouseEnter={playHoverSound} onClick={() => save('')}>
            Forget
          </button>
        )}
      </div>
      {own && !client.valid && client.error && <p className="play-message play-message--error">{client.error}</p>}
      {own && client.valid && (
        <>
          <dl className="play-client-facts">
            <dt>Version</dt><dd>{client.version || 'Unknown'}</dd>
            {client.cpuBaseline && <><dt>Needs</dt><dd>A processor with {client.cpuBaseline}</dd></>}
            <dt>Replays</dt><dd>{client.playback ? 'Can be watched from Tracker' : 'Not in this version (no SysPlayback folder)'}</dd>
          </dl>
          {client.cpuSupported === false && <p className="play-message play-message--error">{CPU_MESSAGE}</p>}
          {engines.compat && (
            <p className="play-settings-help">
              Its compatibility engine (melee_port.exe) can run added games whose fighters have no native code.
            </p>
          )}
        </>
      )}
      {message && <p className={`play-message play-message--${message.kind}`}>{message.text}</p>}
    </div>
  )
}

export default function PlaySettings({ env, client, onChanged, onOpenGameSettings, settingsError, settingsBusy }) {
  const settingsNote = gameSettingsNote(env.gameSettings)
  const ready = !!env.client?.valid
  return (
    <section className="play-settings">
      {client && <ClientCard env={env} client={client} />}

      <div className="play-settings-card">
        <h2>Game settings</h2>
        <p className="play-settings-help">
          Graphics, controls and audio live in the game's own settings window. One set of settings is shared by every game on the shelf.
        </p>
        {settingsNote && <p className="play-settings-help">{settingsNote}</p>}
        <button type="button" className="play-secondary" disabled={!ready || settingsBusy}
          onMouseEnter={playHoverSound} onClick={onOpenGameSettings}>
          {settingsBusy ? 'Settings window open' : 'Open game settings'}
        </button>
        {!ready && <p className="play-settings-help">Install Nucleus Unlocked first.</p>}
        {settingsError && <p className="play-message play-message--error">{settingsError}</p>}
      </div>

      <OwnFolderCard env={env} onChanged={onChanged} />
    </section>
  )
}
