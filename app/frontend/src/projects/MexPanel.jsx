import { useState, useEffect, useRef } from 'react'
// IsoBuilder first: its stylesheet must load ahead of MexPanel.css (as it did when
// the Vault pulled it into a shared chunk), or .btn-gold would start beating .btn-secondary.
import IsoBuilder from './export/IsoBuilder'
import './MexPanel.css'
import './FightersSidebar.css'
import './characters/CostumesPanel.css'
import './ProjectSelector.css'
import './stages/ButtonTokens.css'
import './characters/ExtrasView.css'
import './characters/TeamColors.css'
import './characters/ZeldaSheikPanel.css'
import './MusicModals.css'
import './codes/CodesManagerModal.css'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import ProjectSelector from './ProjectSelector'
import BuildInfoModal from './BuildInfoModal'
import ProjectHeaderInfo from './ProjectHeaderInfo'
import DiscUsageIndicator from './DiscUsageIndicator'
import LargeRosterWarning from './LargeRosterWarning'
import CharacterMode from './CharacterMode'
import StageMode from './StageMode'
import MenuMode from './MenuMode'
import HexagonLoader from '../shared/ui/HexagonLoader'
import MenuMusicModal from './MenuMusicModal'
import CodesManagerModal from './codes/CodesManagerModal'
import { api } from '../shared/transport/api'
import { setProjectGeneration } from '../shared/transport/projectGeneration'
import { orderSavesPending, waitForOrderSaves } from './characters/orderSaves'

const MexPanel = ({ active, vaultMetadata }) => {
  const [mode, setMode] = useState('characters')
  const [mexStatus, setMexStatus] = useState(null)
  const [fighters, setFighters] = useState([])
  const [fightersStatus, setFightersStatus] = useState('loading')
  const fightersRequestRef = useRef(0)
  const [selectedFighter, setSelectedFighter] = useState(null)
  const [storageCostumes, setStorageCostumes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [diagnostics, setDiagnostics] = useState(null)
  const [projectLoaded, setProjectLoaded] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [showIsoBuilder, setShowIsoBuilder] = useState(false)
  const [showProjectModal, setShowProjectModal] = useState(false)
  const [showBuildModal, setShowBuildModal] = useState(false)
  const [showMenuMusic, setShowMenuMusic] = useState(false)
  const [showCodesManager, setShowCodesManager] = useState(false)
  const [buildInfo, setBuildInfo] = useState(null)
  // The backend's count of project opens/closes, from the last status. The
  // workspace below the header is keyed by it, so a switch starts every mode
  // fresh instead of showing the previous project's stage list or selection.
  const [generation, setGeneration] = useState(null)
  // Only the newest status / banner request may write: an older one answering
  // late would bring back a closed project or the previous project's banner.
  const statusRequestRef = useRef(0)
  const buildRequestRef = useRef(0)
  // Switch/Close wait for costume-order saves; this labels the button meanwhile.
  const [waitingForOrderSave, setWaitingForOrderSave] = useState(false)
  const [createProjectOverlay, setCreateProjectOverlay] = useState({
    active: false,
    title: 'Creating Project',
    status: '',
    progress: 0
  })

  useEffect(() => {
    fetchMexStatus()
  }, [])

  useEffect(() => {
    const changed = () => {
      fetchMexStatus()
      if (projectLoaded) { fetchFighters(); fetchBuildInfo() }
    }
    window.addEventListener('nucleus:project-changed', changed)
    return () => window.removeEventListener('nucleus:project-changed', changed)
  }, [projectLoaded])

  useEffect(() => {
    if (projectLoaded) {
      fetchFighters()
      fetchStorageCostumes()
      fetchBuildInfo()
    }
  }, [projectLoaded])

  // The vault (Storage tab) and this install page keep their own copies of the
  // costume list, and both panels stay mounted (just hidden). So a folder move /
  // reorder / retake done in the vault would leave our "Available to Import" list
  // stale. Re-fetch it (a) whenever this tab becomes active, and (b) the moment
  // the vault changes -- App.fetchMetadata runs on every vault mutation and hands
  // us a fresh metadata object -- so the install order always matches the vault.
  useEffect(() => {
    if (active && projectLoaded) fetchStorageCostumes()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  const vaultFirstRef = useRef(true)
  useEffect(() => {
    // Skip the initial value (the projectLoaded effect already loaded the list);
    // only re-fetch on SUBSEQUENT vault changes.
    if (vaultFirstRef.current) { vaultFirstRef.current = false; return }
    if (projectLoaded) fetchStorageCostumes()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vaultMetadata])

  const applyStatus = (data) => {
    setMexStatus(data)
    setProjectLoaded(data.projectLoaded || false)
    if (data.generation !== undefined) {
      setProjectGeneration(data.generation)
      setGeneration(data.generation)
    }
    // A status that arrived is the connection working again.
    setError(null)
    setLoading(false)
  }

  const fetchMexStatus = async () => {
    const request = ++statusRequestRef.current
    try {
      const data = await api.get('/status')
      if (request !== statusRequestRef.current) return
      applyStatus(data)
    } catch (err) {
      if (request !== statusRequestRef.current) return
      if (err.data) {
        // Backend answered with its own status envelope (e.g. connected:false);
        // that used to flow straight into state instead of the error banner.
        applyStatus(err.data)
        return
      }
      setError('Failed to connect to MEX API')
      console.error(err)
      if (window.electron?.getBackendDiagnostics) {
        try {
          const diag = await window.electron.getBackendDiagnostics()
          setDiagnostics(diag)
        } catch (diagErr) {
          console.error('Failed to fetch backend diagnostics:', diagErr)
        }
      }
      setLoading(false)
    }
  }

  const fetchFighters = async () => {
    const request = ++fightersRequestRef.current
    setFightersStatus('loading')
    try {
      const data = await api.get('/fighters')
      if (request !== fightersRequestRef.current) return
      if (!Array.isArray(data.fighters)) throw new Error('Fighter list unavailable')
      setFighters(data.fighters)
      setFightersStatus('ready')
    } catch (err) {
      if (request !== fightersRequestRef.current) return
      setFightersStatus('error')
      console.error('Failed to fetch fighters:', err)
    } finally {
      if (request === fightersRequestRef.current) setLoading(false)
    }
  }

  const fetchStorageCostumes = async () => {
    try {
      const data = await api.get('/api/mex/storage/costumes')
      setStorageCostumes(data.costumes)
    } catch (err) {
      console.error('Failed to fetch storage costumes:', err)
    }
  }

  const fetchBuildInfo = async () => {
    const request = ++buildRequestRef.current
    try {
      const data = await api.get('/project/build')
      if (request !== buildRequestRef.current) return
      setBuildInfo(data)
    } catch (err) {
      console.error('Failed to fetch build info:', err)
    }
  }

  // Costume moves made in this project are saved before it is closed or
  // switched away from (the backend would refuse them once another is open).
  const afterOrderSaves = async (action) => {
    if (orderSavesPending()) {
      setWaitingForOrderSave(true)
      await waitForOrderSaves()
      setWaitingForOrderSave(false)
    }
    action()
  }

  const handleProjectOpened = async () => {
    ++fightersRequestRef.current
    setFightersStatus('loading')
    setFighters([])
    ++buildRequestRef.current
    setBuildInfo(null)  // drop the previous project's banner while the new one loads
    setCreateProjectOverlay((currentState) => currentState.active
      ? {
          ...currentState,
          title: 'Loading Project Data',
          status: 'Refreshing project status and opening the new workspace...',
          progress: Math.max(currentState.progress, 97)
        }
      : currentState)

    await fetchMexStatus()
    setRefreshing(true)

    setCreateProjectOverlay((currentState) => currentState.active
      ? {
          ...currentState,
          title: 'Loading Fighters and Assets',
          status: 'Fetching fighters and available costumes for the new project...',
          progress: Math.max(currentState.progress, 99)
        }
      : currentState)

    await Promise.all([
      fetchFighters(),
      fetchStorageCostumes(),
      fetchBuildInfo()
    ])
    setRefreshing(false)
    setSelectedFighter(null)
  }

  const handleProjectDeleted = async () => {
    ++fightersRequestRef.current
    setFightersStatus('loading')
    await fetchMexStatus()
    setSelectedFighter(null)
    setShowProjectModal(false)
  }

  const handleCloseProject = async () => {
    try {
      await api.post('/project/close')

      ++fightersRequestRef.current
      setFightersStatus('loading')
      setFighters([])

      await fetchMexStatus()
      setSelectedFighter(null)
      setShowProjectModal(false)
      setShowIsoBuilder(false)
    } catch (err) {
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Failed to close project: ${err.message}` : `Error closing project: ${err.message}`)
    }
  }

  const handleOpenProjectFolder = async () => {
    if (!mexStatus?.project?.path) {
      return
    }

    if (!window.electron?.openProjectFolder) {
      alert('Electron API not available. Please run this app in Electron mode.')
      return
    }

    try {
      const result = await window.electron.openProjectFolder(mexStatus.project.path)
      if (!result?.success) {
        alert(`Failed to open project folder: ${result?.error || 'Unknown error'}`)
      }
    } catch (err) {
      alert(`Error opening project folder: ${err.message}`)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await Promise.all([
      fetchFighters(),
      fetchStorageCostumes()
    ])
    setRefreshing(false)
  }

  const renderCreateProjectOverlay = () => {
    if (!createProjectOverlay.active) {
      return null
    }

    return (
      <div className="import-overlay">
        <div className="import-modal import-modal--hexagon">
          <HexagonLoader
            size={116}
            className="import-loader"
            progress={createProjectOverlay.progress}
            label={`Creating project. ${createProjectOverlay.status || 'Working...'}`}
          />
          <h3>{createProjectOverlay.title}</h3>
          <p className="import-status">{createProjectOverlay.status}</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return <div className="mex-panel loading">Loading MEX Manager...</div>
  }

  if (error) {
    const recentOutput = diagnostics?.output?.slice(-20).join('\n')
    return (
      <div className="mex-panel error">
        <h2>MEX Connection Error</h2>
        <p>{error}</p>
        {diagnostics?.startupError && (
          <>
            <p>The bundled backend failed to start:</p>
            <code>{diagnostics.startupError}</code>
          </>
        )}
        {recentOutput && (
          <details className="mex-error-details">
            <summary>Show backend output (paste this when reporting the issue)</summary>
            <pre className="mex-error-log">{recentOutput}</pre>
          </details>
        )}
        {!window.electron && (
          <>
            <p>Make sure the backend is running:</p>
            <code>python backend/app.py</code>
          </>
        )}
      </div>
    )
  }

  // Show project selection screen if no project is loaded
  if (!projectLoaded) {
    return (
      <>
        <ProjectSelector
          active={active}
          showModal={false}
          onProjectOpened={handleProjectOpened}
          onProjectDeleted={handleProjectDeleted}
          onCreateProjectOverlayChange={setCreateProjectOverlay}
        />
        {renderCreateProjectOverlay()}
      </>
    )
  }

  return (
    <>
      <div className="mex-panel">
        <div className="mex-header">
          <div className="header-left">
            {mexStatus?.connected && (
              <ProjectHeaderInfo
                buildInfo={buildInfo}
                projectName={mexStatus.project.path?.split(/[/\\]/).slice(-2, -1)[0] || mexStatus.project.name}
                onOpenBanner={() => setShowBuildModal(true)}
              />
            )}
            {mexStatus?.connected && projectLoaded && (
              <DiscUsageIndicator
                projectLoaded={projectLoaded}
                totalCostumes={(fighters || []).reduce((s, f) => s + (f.costumeCount || 0), 0)}
              />
            )}
            <div className="action-buttons-group">
              <div className="action-buttons-cluster">
                <button
                  className="action-btn"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); handleOpenProjectFolder() }}
                >
                  Open Folder
                </button>
                <button
                  className="action-btn close-project-btn"
                  onMouseEnter={playHoverSound}
                  disabled={waitingForOrderSave}
                  onClick={() => { playSound('back'); afterOrderSaves(handleCloseProject) }}
                >
                  {waitingForOrderSave ? 'Saving order…' : 'Close Project'}
                </button>
                <button
                  className="action-btn"
                  onMouseEnter={playHoverSound}
                  disabled={waitingForOrderSave}
                  onClick={() => { playSound('start'); afterOrderSaves(() => setShowProjectModal(true)) }}
                >
                  {waitingForOrderSave ? 'Saving order…' : 'Switch Project'}
                </button>
                <button
                  className="action-btn codes-btn"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); setShowCodesManager(true); }}
                  title="Manage the gecko codes applied to this build"
                >
                  <span className="codes-btn__glyph">{'{ }'}</span> Codes
                </button>
              </div>
              <button
                className="action-btn export-btn export-btn--tall"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('start'); setShowIsoBuilder(true); }}
              >
                Export
              </button>
            </div>
          </div>
        </div>

        <LargeRosterWarning fighters={fighters} status={fightersStatus} />

        {mode === 'characters' ? (
          <CharacterMode
            key={`characters-${generation}`}
            mode={mode}
            onModeChange={setMode}
            fighters={fighters}
            fightersStatus={fightersStatus}
            onReloadRoster={fetchFighters}
            selectedFighter={selectedFighter}
            onSelectFighter={setSelectedFighter}
            storageCostumes={storageCostumes}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            onOpenMenuMusic={() => setShowMenuMusic(true)}
            vaultMetadata={vaultMetadata}
          />
        ) : mode === 'stages' ? (
          <StageMode
            key={`stages-${generation}`}
            mode={mode}
            onModeChange={setMode}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            onOpenMenuMusic={() => setShowMenuMusic(true)}
          />
        ) : (
          <MenuMode
            key={`menus-${generation}`}
            mode={mode}
            onModeChange={setMode}
            onOpenMenuMusic={() => setShowMenuMusic(true)}
            projectPath={mexStatus?.project?.path || null}
          />
        )}

        <MenuMusicModal
          show={showMenuMusic}
          onClose={() => setShowMenuMusic(false)}
        />

        <CodesManagerModal
          show={showCodesManager}
          onClose={() => setShowCodesManager(false)}
        />

        {showIsoBuilder && (
          <IsoBuilder
            onClose={() => setShowIsoBuilder(false)}
            fighters={fighters}
            fightersStatus={fightersStatus}
            onReloadRoster={fetchFighters}
            projectName={mexStatus?.project?.path?.split(/[/\\]/).slice(-2, -1)[0] || 'game'}
          />
        )}

        {showProjectModal && (
          <ProjectSelector
            active={active}
            showModal={true}
            onClose={() => setShowProjectModal(false)}
            onProjectOpened={handleProjectOpened}
            onProjectDeleted={handleProjectDeleted}
            onCreateProjectOverlayChange={setCreateProjectOverlay}
          />
        )}

        <BuildInfoModal
          show={showBuildModal}
          onClose={() => { setShowBuildModal(false); fetchBuildInfo() }}
        />
      </div>

      {renderCreateProjectOverlay()}
    </>
  )
}

export default MexPanel
