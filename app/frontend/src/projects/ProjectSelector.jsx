/**
 * ProjectSelector - MEX project selection and management
 *
 * Features:
 * - Unified project catalog for managed and external projects
 * - Open existing .mexproj file
 * - Create new project from vanilla ISO
 * - Project switching modal
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { appAlert, appConfirm } from '../shared/ui/appDialogs'
import HexagonLoader from '../shared/ui/HexagonLoader'
import { backendMediaUrl } from '../shared/config/config'
import { api } from '../shared/transport/api'
import { setProjectGeneration } from '../shared/transport/projectGeneration'
import {
  getProjectDisplayName, getProjectDirectory, isManagedProject, mergeProjectCollections,
  readStoredProjects, rememberProject, forgetProject,
} from './projectCatalog'
import { DAS_NOTICE_TITLE, dasInstallFailureNotice, dasInstallNotice } from './stages/dasInstall'

export default function ProjectSelector({
  active = true,
  showModal,
  onClose,
  onProjectOpened,
  onProjectDeleted,
  onCreateProjectOverlayChange,
}) {
  const [projects, setProjects] = useState([])
  const [projectsLoading, setProjectsLoading] = useState(true)
  const [projectsError, setProjectsError] = useState('')
  const projectLoadVersion = useRef(0)
  const [openingProject, setOpeningProject] = useState(false)
  const [creatingProject, setCreatingProject] = useState(false)
  const [deletingProjectPath, setDeletingProjectPath] = useState('')
  const [createProjectTitle, setCreateProjectTitle] = useState('Creating Project')
  const [createProjectStatus, setCreateProjectStatus] = useState('')
  const [createProjectProgress, setCreateProjectProgress] = useState(0)
  const [showCreateProjectNameModal, setShowCreateProjectNameModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('My Project')
  const [createProjectNameError, setCreateProjectNameError] = useState('')
  const [availablePatches, setAvailablePatches] = useState([])
  const [patchesLoading, setPatchesLoading] = useState(false)
  const [selectedPatchId, setSelectedPatchId] = useState('')
  const [showPatchPickerModal, setShowPatchPickerModal] = useState(false)
  const createProjectNameInputRef = useRef(null)
  // True only when a mousedown started on the overlay backdrop itself — a drag
  // that starts inside the modal (e.g. selecting text in the name input) and
  // releases over the backdrop must not close the modal and eat the typed name.
  const nameOverlayMouseDownRef = useRef(false)

  const syncCreateProjectOverlay = (nextState) => {
    const overlayState = {
      active: false,
      title: 'Creating Project',
      status: '',
      progress: 0,
      ...nextState
    }

    if (!onCreateProjectOverlayChange) {
      setCreateProjectTitle(overlayState.title)
      setCreateProjectStatus(overlayState.status)
      setCreateProjectProgress(overlayState.progress)
    }
    onCreateProjectOverlayChange?.(overlayState)
  }

  const clearCreateProjectOverlay = () => {
    syncCreateProjectOverlay({
      active: false,
      title: 'Creating Project',
      status: '',
      progress: 0
    })
  }

  async function loadProjects() {
    const version = ++projectLoadVersion.current
    const storedProjects = readStoredProjects()

    setProjectsLoading(true)
    setProjectsError('')

    try {
      const data = await api.get('/project/list')
      if (version !== projectLoadVersion.current) return
      setProjects(mergeProjectCollections(storedProjects, data.projects || []))
    } catch (err) {
      if (version !== projectLoadVersion.current) return
      console.error('Failed to load project catalog:', err)
      setProjects(mergeProjectCollections(storedProjects, []))
      setProjectsError(
        storedProjects.length > 0
          ? 'Could not refresh managed projects. Showing saved external projects only.'
          : 'Could not load the project list.'
      )
    } finally {
      if (version === projectLoadVersion.current) setProjectsLoading(false)
    }
  }

  useEffect(() => {
    const changed = () => loadProjects()
    window.addEventListener('nucleus:project-changed', changed)
    return () => {
      window.removeEventListener('nucleus:project-changed', changed)
      projectLoadVersion.current++
    }
  }, [])

  useEffect(() => {
    if (active) loadProjects()
  }, [active])

  useEffect(() => {
    if (showCreateProjectNameModal) {
      requestAnimationFrame(() => {
        createProjectNameInputRef.current?.focus()
        createProjectNameInputRef.current?.select()
      })
    }
  }, [showCreateProjectNameModal])

  const handleOpenProjectFromPath = async (projectPath) => {
    setOpeningProject(true)

    try {
      console.log('Opening project:', projectPath)

      const data = await api.post('/project/open', { projectPath })
      setProjectGeneration(data.generation)

      console.log('[OK] Project opened:', data.project.name)
      rememberProject(projectPath, data.project.name, data.project)
      await onProjectOpened()
      if (onClose) {
        onClose()
      }
    } catch (err) {
      alert(`Failed to open project: ${err.message}`)
    } finally {
      setOpeningProject(false)
    }
  }

  const handleOpenProject = async () => {
    if (!window.electron) {
      alert('Electron API not available. Please run this app in Electron mode.')
      return
    }

    setOpeningProject(true)

    try {
      const filePath = await window.electron.openProjectDialog()

      if (!filePath) {
        return
      }

      console.log('Selected project:', filePath)

      const data = await api.post('/project/open', { projectPath: filePath })
      setProjectGeneration(data.generation)

      console.log('[OK] Project opened:', data.project.name)
      rememberProject(filePath, data.project.name, data.project)
      await onProjectOpened()
      if (onClose) {
        onClose()
      }
    } catch (err) {
      alert(`Failed to open project: ${err.message}`)
    } finally {
      setOpeningProject(false)
    }
  }

  const loadAvailablePatches = async () => {
    setPatchesLoading(true)
    try {
      const data = await api.get('/xdelta/list')
      setAvailablePatches(data.patches || [])
    } catch (err) {
      console.error('Failed to load vault patches:', err)
      setAvailablePatches([])
    } finally {
      setPatchesLoading(false)
    }
  }

  const openCreateProjectNameModal = (patchId = '') => {
    setNewProjectName('My Project')
    setCreateProjectNameError('')
    setSelectedPatchId(patchId)
    setShowCreateProjectNameModal(true)
  }

  const openPatchPicker = () => {
    setShowPatchPickerModal(true)
    loadAvailablePatches()
  }

  const handlePatchPicked = (patch) => {
    setShowPatchPickerModal(false)
    openCreateProjectNameModal(patch.id)
  }

  const closeCreateProjectNameModal = () => {
    if (creatingProject) {
      return
    }

    setShowCreateProjectNameModal(false)
    setCreateProjectNameError('')
  }

  const handleCreateProject = async (projectName, patchId = '') => {
    if (!window.electron) {
      alert('Electron API not available. Please run this app in Electron mode.')
      return
    }

    const selectedPatch = patchId
      ? availablePatches.find((patch) => patch.id === patchId)
      : null
    const preparingStatus = selectedPatch
      ? `Applying "${selectedPatch.name}" to your vanilla ISO and preparing the project...`
      : 'Preparing a managed project from your vanilla ISO...'

    const createProjectRequest = async (isoPath) =>
      api.post('/project/create', {
        isoPath,
        projectName,
        patchId: patchId || undefined,
        starterCodes: true,
      })

    let isoPath = localStorage.getItem('vanilla_iso_path')

    if (!isoPath) {
      isoPath = await window.electron.openIsoDialog()

      if (!isoPath) {
        return
      }
    } else {
      console.log('Using saved vanilla ISO path:', isoPath)
    }

    console.log('Selected ISO:', isoPath)

    // Shown once the project is open and the overlay is gone (see below).
    let dasNotice = null
    setCreatingProject(true)
    syncCreateProjectOverlay({
      active: true,
      title: 'Creating Workspace',
      progress: 14,
      status: preparingStatus
    })

    try {
      let data
      try {
        data = await createProjectRequest(isoPath)
      } catch (createErr) {
        if (!(createErr.status === 404 && createErr.message?.includes('ISO file not found'))) {
          alert(`Failed to create project: ${createErr.message}`)
          return
        }
        localStorage.removeItem('vanilla_iso_path')
        syncCreateProjectOverlay({
          active: true,
          title: 'Vanilla ISO Missing',
          progress: 8,
          status: 'Saved ISO path could not be found. Select your ISO again...'
        })

        const replacementIsoPath = await window.electron.openIsoDialog()
        if (!replacementIsoPath) {
          return
        }

        isoPath = replacementIsoPath
        syncCreateProjectOverlay({
          active: true,
          title: 'Creating Workspace',
          progress: 14,
          status: preparingStatus
        })
        try {
          data = await createProjectRequest(isoPath)
        } catch (retryErr) {
          alert(`Failed to create project: ${retryErr.message}`)
          return
        }
      }

      console.log('[OK] Project created:', data.projectPath)

      localStorage.setItem('vanilla_iso_path', isoPath)
      console.log('[OK] Saved vanilla ISO path:', isoPath)

      syncCreateProjectOverlay({
        active: true,
        title: 'Opening Project',
        progress: 56,
        status: 'Project files are ready. Opening them in Nucleus...'
      })
      let openData
      try {
        openData = await api.post('/project/open', { projectPath: data.projectPath })
        setProjectGeneration(openData.generation)
      } catch (openErr) {
        alert(`Project created but failed to open: ${openErr.message}`)
        return
      }

      console.log('[OK] Project opened:', openData.project.name)
      rememberProject(data.projectPath, openData.project.name, {
        projectDirectory: data.projectDirectory,
        isManagedProject: data.isManagedProject,
        lastModifiedAt: Math.floor(Date.now() / 1000)
      })

      syncCreateProjectOverlay({
        active: true,
        title: 'Installing Stage Variants',
        progress: 84,
        status: 'Setting up Dynamic Alternate Stages for the new project...'
      })
      console.log('Installing DAS framework...')
      try {
        // A stage whose loader could not be made comes back as `warning`.
        dasNotice = dasInstallNotice(await api.post('/das/install'))
        console.log('[OK] DAS framework installed')
      } catch (dasErr) {
        console.error('DAS installation error:', dasErr)
        dasNotice = dasInstallFailureNotice(dasErr)
      }

      syncCreateProjectOverlay({
        active: true,
        title: 'Loading Project Data',
        progress: 96,
        status: 'Loading fighters, stages, and vault data...'
      })
      await onProjectOpened()
      if (onClose) {
        onClose()
      }
    } catch (err) {
      dasNotice = null
      alert(`Error creating project: ${err.message}`)
    } finally {
      setCreatingProject(false)
      clearCreateProjectOverlay()
    }
    if (dasNotice) {
      appAlert(dasNotice, { title: DAS_NOTICE_TITLE })
    }
  }

  const handleCreateProjectNameSubmit = async (event) => {
    event.preventDefault()

    const trimmedProjectName = newProjectName.trim()
    if (!trimmedProjectName) {
      setCreateProjectNameError('Enter a project name.')
      return
    }

    setShowCreateProjectNameModal(false)
    setCreateProjectNameError('')
    await handleCreateProject(trimmedProjectName, selectedPatchId)
  }

  const renderCreateProjectOverlay = () => {
    if (!creatingProject) {
      return null
    }

    return (
      <div className="import-overlay">
        <div className="import-modal import-modal--hexagon">
          <HexagonLoader
            size={116}
            className="import-loader"
            progress={createProjectProgress}
            label={`Creating project. ${createProjectStatus || 'Working...'}`}
          />
          <h3>{createProjectTitle}</h3>
          <p className="import-status">{createProjectStatus}</p>
        </div>
      </div>
    )
  }

  const renderCreateProjectNameModal = () => {
    if (!showCreateProjectNameModal) {
      return null
    }

    return (
      <div
        className="project-name-modal-overlay"
        onMouseDown={(event) => { nameOverlayMouseDownRef.current = event.target === event.currentTarget }}
        onClick={(event) => {
          if (event.target === event.currentTarget && nameOverlayMouseDownRef.current) {
            playSound('back')
            closeCreateProjectNameModal()
          }
          nameOverlayMouseDownRef.current = false
        }}
      >
        <div className="project-name-modal" onClick={(event) => event.stopPropagation()}>
          <form
            className="project-name-form"
            onSubmit={handleCreateProjectNameSubmit}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                playSound('back')
                closeCreateProjectNameModal()
              }
            }}
          >
            <h3>Name New Project</h3>
            <p>Choose a name for your new project.</p>
            <input
              ref={createProjectNameInputRef}
              className="project-name-input"
              type="text"
              value={newProjectName}
              onChange={(event) => {
                setNewProjectName(event.target.value)
                if (createProjectNameError) {
                  setCreateProjectNameError('')
                }
              }}
              placeholder="Project name"
              maxLength={80}
            />
            {selectedPatchId && (
              <p className="project-start-from-note">
                Starting from patch:{' '}
                <strong>{availablePatches.find((patch) => patch.id === selectedPatchId)?.name || 'Vault patch'}</strong>
              </p>
            )}
            {createProjectNameError && (
              <p className="project-name-error">{createProjectNameError}</p>
            )}
            <div className="project-name-actions">
              <button
                type="button"
                className="btn-cancel-modal"
                onMouseEnter={playHoverSound}
                onClick={() => {
                  playSound('back')
                  closeCreateProjectNameModal()
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="project-btn"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('start') }}
              >
                Create Project
              </button>
            </div>
          </form>
        </div>
      </div>
    )
  }

  const renderPatchPickerModal = () => {
    if (!showPatchPickerModal) {
      return null
    }

    return (
      <div className="project-name-modal-overlay" onClick={() => setShowPatchPickerModal(false)}>
        <div className="project-name-modal" onClick={(event) => event.stopPropagation()}>
          <div className="patch-picker">
            <h3>Create From Patch</h3>
            <p>Pick a patch from your vault. It's applied to a temporary copy of your vanilla ISO to build the project — your original vanilla ISO is never modified.</p>
            <p className="patch-picker-note">
              Only works with patches built on vanilla Melee (texture and visual mods).
              Patches that overhaul the game itself won't convert correctly.
            </p>
            {patchesLoading ? (
              <p className="patch-picker-empty">Loading patches...</p>
            ) : availablePatches.length === 0 ? (
              <p className="patch-picker-empty">No patches in your vault yet. Import one from the Vault's Patches tab first.</p>
            ) : (
              <div className="patch-picker-list">
                {availablePatches.map((patch) => (
                  <button
                    key={patch.id}
                    type="button"
                    className="patch-picker-item"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('start'); handlePatchPicked(patch) }}
                  >
                    {patch.imageUrl ? (
                      <img className="patch-picker-cover" src={backendMediaUrl(patch.imageUrl)} alt="" />
                    ) : (
                      <span className="patch-picker-monogram">{(patch.name?.trim()?.[0] || '?').toUpperCase()}</span>
                    )}
                    <span className="patch-picker-details">
                      <span className="patch-picker-name">{patch.name}</span>
                      {patch.description && <span className="patch-picker-desc">{patch.description}</span>}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="project-name-actions">
              <button
                type="button"
                className="btn-cancel-modal"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('back'); setShowPatchPickerModal(false) }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const handleOpenProjectFolder = async (project) => {
    if (!window.electron?.openProjectFolder) {
      alert('Electron API not available. Please run this app in Electron mode.')
      return
    }

    try {
      const result = await window.electron.openProjectFolder(project.path)
      if (!result?.success) {
        alert(`Failed to open project folder: ${result?.error || 'Unknown error'}`)
      }
    } catch (err) {
      alert(`Error opening project folder: ${err.message}`)
    }
  }

  const handleDeleteProject = async (project) => {
    const projectName = getProjectDisplayName(project)
    const projectDirectory = getProjectDirectory(project)

    const confirmed = await appConfirm(
      `Delete "${projectName}" and its project folder?\n\n${projectDirectory}\n\nThis cannot be undone.`,
      {
        title: 'Delete Project',
        confirmText: 'Delete',
      }
    )

    if (!confirmed) {
      return
    }

    setDeletingProjectPath(project.path)

    try {
      const data = await api.post('/project/delete', { projectPath: project.path })

      forgetProject(project.path)
      await loadProjects()

      if (data.currentProjectClosed && onProjectDeleted) {
        await onProjectDeleted()
      }

      if (data.currentProjectClosed && onClose) {
        onClose()
      }
    } catch (err) {
      alert(`Failed to delete project: ${err.message}`)
      // The backend closes the project before removing its folder; a failed
      // removal still closed it, and the panel must not keep showing it.
      if (err.data?.currentProjectClosed) {
        await loadProjects()
        if (onProjectDeleted) await onProjectDeleted()
        if (onClose) onClose()
      }
    } finally {
      setDeletingProjectPath('')
    }
  }

  const handleRemoveProject = async (projectPath) => {
    forgetProject(projectPath)
    await loadProjects()
  }

  const renderProjectItem = (project, idx, className) => {
    const managedProject = isManagedProject(project)
    const isDeleting = deletingProjectPath === project.path
    const itemClassName = `${className}${project.isCurrentProject ? ' project-list-item--current' : ''}`

    const managementAction = managedProject
      ? {
          className: 'recent-project-delete',
          label: isDeleting ? '...' : 'Delete',
          title: 'Delete project',
          disabled: isDeleting,
          sound: 'boop',
          onClick: () => handleDeleteProject(project)
        }
      : {
          className: 'recent-project-remove',
          label: 'Remove',
          title: 'Remove project from list',
          disabled: false,
          sound: 'boop',
          onClick: () => handleRemoveProject(project.path)
        }

    return (
      <div
        key={project.path || idx}
        className={itemClassName}
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('start'); handleOpenProjectFromPath(project.path) }}
      >
        <div className="recent-project-details">
          <div className="project-entry-header">
            <div className="recent-project-name">{getProjectDisplayName(project)}</div>
            <div className="project-entry-badges">
              {project.isCurrentProject && (
                <span className="project-entry-badge project-entry-badge-current">Current</span>
              )}
            </div>
          </div>
          <div className="recent-project-path">{project.path}</div>
        </div>
        <div className="recent-project-actions">
          <button
            className="recent-project-action recent-project-open"
            onMouseEnter={playHoverSound}
            onClick={(event) => {
              event.stopPropagation()
              playSound('start')
              handleOpenProjectFolder(project)
            }}
            title="Open project folder"
          >
            Folder
          </button>
          <button
            className={`recent-project-action ${managementAction.className}`}
            onMouseEnter={playHoverSound}
            onClick={(event) => {
              event.stopPropagation()
              playSound(managementAction.sound)
              managementAction.onClick()
            }}
            title={managementAction.title}
            disabled={managementAction.disabled}
          >
            {managementAction.label}
          </button>
        </div>
      </div>
    )
  }

  const viewConfig = showModal
    ? {
        title: 'Switch Project',
        headingTag: 'h2',
        projectListClassName: 'recent-projects-list-modal',
        projectItemClassName: 'recent-project-item-modal',
        projectOptionsClassName: 'project-options-modal',
        projectOptionClassName: 'project-option-modal',
        openProjectDescription: ''
      }
    : {
        title: 'Install',
        headingTag: 'h1',
        projectListClassName: 'recent-projects-list',
        projectItemClassName: 'recent-project-item',
        projectOptionsClassName: 'project-options',
        projectOptionClassName: 'project-option',
        openProjectDescription: ''
      }

  const HeadingTag = viewConfig.headingTag
  const projectCountLabel = projectsLoading && projects.length === 0
    ? 'Loading...'
    : `${projects.length} ${projects.length === 1 ? 'project' : 'projects'}`

  const projectActions = [
    {
      key: 'open-existing',
      title: 'Open Existing Project',
      description: viewConfig.openProjectDescription,
      buttonLabel: openingProject ? 'Opening...' : 'Browse for .mexproj',
      disabled: openingProject,
      onClick: handleOpenProject
    },
    {
      key: 'create-new',
      title: 'Create New Project',
      description: '',
      buttonLabel: creatingProject ? 'Creating Project...' : 'Create Project',
      disabled: creatingProject || showCreateProjectNameModal,
      onClick: openCreateProjectNameModal,
      squareAction: {
        title: 'Create from a vault patch',
        onClick: openPatchPicker
      }
    }
  ]

  const PatchIcon = ({ size = 20 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="3" y="8.4" width="18" height="7.2" rx="3.6" transform="rotate(-45 12 12)" />
      <circle cx="10.6" cy="10.6" r="0.5" fill="currentColor" stroke="none" />
      <circle cx="13.4" cy="13.4" r="0.5" fill="currentColor" stroke="none" />
      <circle cx="13.4" cy="10.6" r="0.5" fill="currentColor" stroke="none" />
      <circle cx="10.6" cy="13.4" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  )

  const renderProjectListBody = () => {
    if (!projects.length) {
      return (
        <div className="project-list-empty">
          {projectsLoading ? 'Loading projects...' : 'No projects yet. Create a new project or browse for a .mexproj file.'}
        </div>
      )
    }

    return (
      <div className={`${viewConfig.projectListClassName} project-list-scroll`}>
        {projects.map((project, idx) => (
          renderProjectItem(project, idx, viewConfig.projectItemClassName)
        ))}
      </div>
    )
  }

  const projectManagementMenu = (
    <div className={`project-management-shell${showModal ? ' project-management-shell--modal' : ''}`}>
      {showModal && (
        <div className="project-management-header">
          <HeadingTag>{viewConfig.title}</HeadingTag>
        </div>
      )}

      <div className={`project-management-body${showModal ? ' project-management-body--modal' : ''}`}>
        <section className="project-list-panel">
          <div className="project-section-heading">
            <span className="project-list-count">{projectCountLabel}</span>
          </div>

          {projectsError && (
            <p className="project-list-notice">{projectsError}</p>
          )}

          {renderProjectListBody()}
        </section>

        <section className="project-actions-panel">
          <div className={viewConfig.projectOptionsClassName}>
            {projectActions.map((action) => (
              <div key={action.key} className={viewConfig.projectOptionClassName}>
                <h3>{action.title}</h3>
                {action.description && <p>{action.description}</p>}
                <div className="project-btn-row">
                  <button
                    className="project-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => {
                      playSound('start')
                      action.onClick()
                    }}
                    disabled={action.disabled}
                  >
                    {action.buttonLabel}
                  </button>
                  {action.squareAction && (
                    <button
                      className="project-btn project-btn-square"
                      onMouseEnter={playHoverSound}
                      onClick={() => {
                        playSound('start')
                        action.squareAction.onClick()
                      }}
                      disabled={action.disabled}
                      title={action.squareAction.title}
                      aria-label={action.squareAction.title}
                    >
                      <PatchIcon />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {showModal && (
            <button
              className="btn-cancel-modal"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); onClose() }}
            >
              Cancel
            </button>
          )}
        </section>
      </div>
    </div>
  )

  if (!showModal) {
    return (
      <div className="mex-panel">
        <div className="project-selection">{projectManagementMenu}</div>

        {renderPatchPickerModal()}
        {renderCreateProjectNameModal()}
        {!onCreateProjectOverlayChange && renderCreateProjectOverlay()}
      </div>
    )
  }

  return (
    <div className="project-modal-overlay" onClick={onClose}>
      <div className="project-modal-content" onClick={(event) => event.stopPropagation()}>
        {projectManagementMenu}
      </div>

      {renderPatchPickerModal()}
      {renderCreateProjectNameModal()}
      {!onCreateProjectOverlayChange && renderCreateProjectOverlay()}
    </div>
  )
}
