/**
 * PlayApp - Play mode: Nucleus's launcher for its game client (gate play; App.jsx reaches this
 * file only through import.meta.glob, so a build without Play carries none of it).
 *
 * Games: the shelf (the built-in Nucleus and Vanilla, then every game added from an export,
 * and one being added), the Slippi account the games sign in with, and the game's own
 * settings window. Each card has its Play button, where to play it, and its menu; with no client
 * installed the built-in cards' button installs it from the signed client feed (usePlayClient).
 * Settings: the installed client and its updates, and the developer's own client folder.
 * Both sit in the app's page shell (.play-shell: the width and padding of the Vault, Tracker and
 * Settings pages).
 */
import { useState } from 'react'
import { playHoverSound } from '../shared/audio/sounds'
import { useActiveJob, useJobEnd } from '../shared/jobs/useJobs'
import AccountLine from './AccountLine'
import AddingCard from './AddingCard'
import { EntryMenu, TargetChooser } from './EntryActions'
import PlaySettings from './PlaySettings'
import ShelfGrid from './ShelfGrid'
import { replacedEntry } from './playCards'
import { SHELF_ADD_KIND, usePlayShelf } from './usePlayShelf'
import { SETTINGS_KEY, usePlayLaunch } from './usePlayLaunch'
import { usePlayClient } from './usePlayClient'
import './play.css'

export { PlayTabs, PLAY_TABS } from './PlayTabs'

function PlayPage({ children }) {
  return (
    <main className="app-content play-app mode-enter">
      <div className="play-shell">{children}</div>
    </main>
  )
}

export default function PlayApp({ activeTab = 'games', onTabChange, visible = true }) {
  const shelf = usePlayShelf(visible)
  const launcher = usePlayLaunch(() => shelf.reload())
  const client = usePlayClient(visible, shelf.reload)
  const adding = useActiveJob(SHELF_ADD_KIND)
  const [coverVersions, setCoverVersions] = useState({})
  const coverChanged = (id) => setCoverVersions((current) => ({ ...current, [id]: Date.now() }))
  // A replaced game keeps its id, so its cover's address: ask for the picture again.
  useJobEnd(SHELF_ADD_KIND, (job) => { const id = replacedEntry(job); if (id) coverChanged(id) })
  const env = { ...shelf.env, install: client.job }
  const settingsOpen = launcher.active?.params?.settingsWindow === true
  const reloadAll = () => { launcher.clearErrors(); return shelf.reload() }

  if (shelf.error && !shelf.loaded) {
    return (
      <PlayPage>
        <p className="play-banner play-banner--error">{shelf.error}</p>
      </PlayPage>
    )
  }

  if (activeTab === 'settings') {
    return (
      <PlayPage>
        <PlaySettings env={env} client={client} onChanged={reloadAll} onOpenGameSettings={launcher.openGameSettings}
          settingsError={launcher.errors[SETTINGS_KEY]} settingsBusy={settingsOpen} />
      </PlayPage>
    )
  }

  const unsupported = env.platform?.supported === false
  // The built-in cards install the client themselves; a banner only for a hand-picked folder that broke.
  const brokenFolder = !unsupported && shelf.loaded && env.client?.source === 'folder' && !env.client.valid
  return (
    <PlayPage>
      <header className="play-header">
        <div className="play-heading">
          <h2 className="play-title">Your games</h2>
          <AccountLine visible={visible} />
        </div>
        <button type="button" className="btn-secondary play-header-button"
          disabled={!env.client?.valid || settingsOpen || unsupported}
          onMouseEnter={playHoverSound} onClick={launcher.openGameSettings}>
          {settingsOpen ? 'Settings window open' : 'Game settings'}
        </button>
      </header>
      {launcher.errors[SETTINGS_KEY] && <p className="play-banner play-banner--error">{launcher.errors[SETTINGS_KEY]}</p>}
      {unsupported && <p className="play-banner">{env.platform.message || 'Nucleus Unlocked is Windows only for now.'}</p>}
      {client.error && <p className="play-banner play-banner--error" role="alert">{client.error}</p>}
      {brokenFolder && (
        <p className="play-banner">
          {"Your own client folder can't be used. "}
          <button type="button" className="play-link" onClick={() => onTabChange?.('settings')}>Open Unlocked settings</button>
        </p>
      )}
      <ShelfGrid
        entries={shelf.entries}
        env={env}
        launcher={launcher}
        client={client}
        adding={<AddingCard job={adding} />}
        coverVersions={coverVersions}
        renderActions={(entry, { target, setTarget }) => {
          const running = launcher.active?.params?.entryId === entry.id
          return (
            <>
              <EntryMenu entry={entry} running={running} onChanged={shelf.reload} onError={launcher.setError}
                onCoverChanged={coverChanged} />
              <TargetChooser entry={entry} target={target} setTarget={setTarget} disabled={running} />
            </>
          )
        }}
      />
    </PlayPage>
  )
}
