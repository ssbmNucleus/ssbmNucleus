// The project list's records: external projects remembered in localStorage
// (migrating the legacy keys), merged with the backend's managed projects,
// normalised and sorted (current first, then most recently opened).

const EXTERNAL_PROJECTS_STORAGE_KEY = 'mex_external_projects'
const LEGACY_PROJECTS_STORAGE_KEY = 'mex_recent_projects'
const LEGACY_KNOWN_PROJECTS_STORAGE_KEY = 'mex_known_projects'

function inferManagedProjectFromPath(projectPath) {
  if (!projectPath) {
    return false
  }

  return /[\\/]projects[\\/][^\\/]+[\\/][^\\/]+\.mexproj$/i.test(projectPath)
}

export function getProjectDisplayName(project) {
  return project.path?.split(/[/\\]/).slice(-2, -1)[0] || project.name
}

export function getProjectDirectory(project) {
  if (project.projectDirectory) {
    return project.projectDirectory
  }

  return project.path?.replace(/[\\/][^\\/]+$/, '') || ''
}

export function isManagedProject(project) {
  if (typeof project.isManagedProject === 'boolean') {
    return project.isManagedProject
  }

  return inferManagedProjectFromPath(project.path)
}

function normalizeProjectRecord(project) {
  if (!project?.path) {
    return null
  }

  const lastOpenedAt = Number.isFinite(project.lastOpenedAt)
    ? project.lastOpenedAt
    : Number.isFinite(project.timestamp)
      ? project.timestamp
      : 0

  const lastModifiedAt = Number.isFinite(project.lastModifiedAt)
    ? project.lastModifiedAt
    : 0

  return {
    path: project.path,
    name: project.name || project.path?.split(/[/\\]/).slice(-2, -1)[0] || 'Project',
    projectDirectory: project.projectDirectory || project.path.replace(/[\\/][^\\/]+$/, ''),
    isManagedProject: typeof project.isManagedProject === 'boolean'
      ? project.isManagedProject
      : inferManagedProjectFromPath(project.path),
    isCurrentProject: Boolean(project.isCurrentProject),
    lastOpenedAt,
    lastModifiedAt
  }
}

function compareProjects(left, right) {
  if (left.isCurrentProject !== right.isCurrentProject) {
    return left.isCurrentProject ? -1 : 1
  }

  if (left.lastOpenedAt !== right.lastOpenedAt) {
    return right.lastOpenedAt - left.lastOpenedAt
  }

  if (left.lastModifiedAt !== right.lastModifiedAt) {
    return right.lastModifiedAt - left.lastModifiedAt
  }

  return getProjectDisplayName(left).localeCompare(getProjectDisplayName(right), undefined, { sensitivity: 'base' })
}

export function mergeProjectCollections(externalProjects, managedProjects) {
  const projectMap = new Map()

  externalProjects
    .map(normalizeProjectRecord)
    .filter(Boolean)
    .forEach((project) => {
      projectMap.set(project.path, project)
    })

  managedProjects
    .map(normalizeProjectRecord)
    .filter(Boolean)
    .forEach((project) => {
      const savedProject = projectMap.get(project.path)

      projectMap.set(project.path, {
        ...savedProject,
        ...project,
        name: savedProject?.name || project.name,
        lastOpenedAt: savedProject?.lastOpenedAt || project.lastOpenedAt
      })
    })

  return Array.from(projectMap.values()).sort(compareProjects)
}

function writeStoredProjects(projectEntries) {
  try {
    const normalizedProjects = projectEntries
      .map(normalizeProjectRecord)
      .filter(Boolean)
      .filter((project) => !isManagedProject(project))
      .sort(compareProjects)
      .map((project) => ({
        path: project.path,
        name: project.name,
        projectDirectory: project.projectDirectory,
        isManagedProject: false,
        lastOpenedAt: project.lastOpenedAt,
        lastModifiedAt: project.lastModifiedAt
      }))

    localStorage.setItem(EXTERNAL_PROJECTS_STORAGE_KEY, JSON.stringify(normalizedProjects))
    localStorage.removeItem(LEGACY_KNOWN_PROJECTS_STORAGE_KEY)
    localStorage.removeItem(LEGACY_PROJECTS_STORAGE_KEY)
  } catch (err) {
    console.error('Failed to save external projects:', err)
  }
}

export function readStoredProjects() {
  try {
    const storedProjects = localStorage.getItem(EXTERNAL_PROJECTS_STORAGE_KEY)
    const legacyKnownProjects = localStorage.getItem(LEGACY_KNOWN_PROJECTS_STORAGE_KEY)
    const legacyProjects = localStorage.getItem(LEGACY_PROJECTS_STORAGE_KEY)
    const rawProjects = storedProjects || legacyKnownProjects || legacyProjects

    if (!rawProjects) {
      return []
    }

    const parsedJson = JSON.parse(rawProjects)
    const parsedProjects = Array.isArray(parsedJson)
      ? parsedJson
      : []

    const normalizedProjects = parsedProjects
      .map(normalizeProjectRecord)
      .filter(Boolean)
      .filter((project) => !isManagedProject(project))
      .sort(compareProjects)

    const shouldRewriteStorage = !storedProjects
      || Boolean(legacyKnownProjects)
      || Boolean(legacyProjects)
      || normalizedProjects.length !== parsedProjects.length

    if (shouldRewriteStorage) {
      writeStoredProjects(normalizedProjects)
    }

    return normalizedProjects
  } catch (err) {
    console.error('Failed to load saved external projects:', err)
    return []
  }
}

export function rememberProject(projectPath, projectName, projectMeta = {}) {
  const projectIsManaged = typeof projectMeta.isManagedProject === 'boolean'
    ? projectMeta.isManagedProject
    : inferManagedProjectFromPath(projectPath)

  if (projectIsManaged) {
    forgetProject(projectPath)
    return
  }

  const storedProjects = readStoredProjects().filter((project) => project.path !== projectPath)

  storedProjects.unshift({
    path: projectPath,
    name: projectName,
    projectDirectory: projectMeta.projectDirectory || projectPath?.replace(/[\\/][^\\/]+$/, ''),
    isManagedProject: false,
    lastOpenedAt: Date.now(),
    lastModifiedAt: projectMeta.lastModifiedAt || 0
  })

  writeStoredProjects(storedProjects)
}

export function forgetProject(projectPath) {
  const storedProjects = readStoredProjects().filter((project) => project.path !== projectPath)
  writeStoredProjects(storedProjects)
}
