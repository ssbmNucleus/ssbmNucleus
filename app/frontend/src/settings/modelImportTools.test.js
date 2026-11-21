import assert from 'node:assert/strict'
import test from 'node:test'
import { KIND, chatToolsView, importToolsNeed, isActiveJob, jobPercent, partText, sizeText, sourceLines, toolsView } from './modelImportTools.js'

// The backend's own sources (service.SOURCES): PyPI's carries parentheses of its own.
const PIECES = [
  { name: 'blender', label: 'Blender 4.3.2', source: 'download.blender.org', size: 400e6, installed: false },
  { name: 'python', label: 'Python 3.13.17', source: 'python.org', size: 11e6, installed: false },
  { name: 'wheels', label: 'bpy 5.2.2, numpy 2.5.3 and 11 more', source: 'PyPI (files.pythonhosted.org)', size: 380e6, installed: false },
]
const status = (fields = {}) => ({ platform: 'win-x64', supported: true, state: 'not_installed', download_bytes: 791e6,
  needed_bytes: 791e6, disk_bytes: 1.62e9, disk_estimated: true, pieces: PIECES, path: 'C:\\Data\\tools\\model-import',
  job: null, error: null, ...fields })

test('sizes read in MB below a gigabyte and in GB with one decimal above', () => {
  assert.equal(sizeText(791e6), '791 MB')
  assert.equal(sizeText(1.62e9), '1.6 GB')
  assert.equal(sizeText(2e9), '2 GB')
  assert.equal(sizeText(12345), 'under 1 MB')
  assert.equal(sizeText(0), null)
  assert.equal(sizeText(undefined), null)
  assert.equal(sizeText('x'), null)
})

test('how much of a download is in reads in one unit when both are in MB', () => {
  assert.equal(partText(168e6, 779e6), '168 of 779 MB')
  assert.equal(partText(168e6, 1.1e9), '168 MB of 1.1 GB')
  assert.equal(partText(2e5, 779e6), 'under 1 MB of 779 MB')
  assert.equal(partText(0, 779e6), '0 MB of 779 MB')
  assert.equal(partText(168e6, 0), null)
})

test('a job\'s progress is a whole percent, or none', () => {
  assert.equal(jobPercent({ progress: 0.426 }), 43)
  assert.equal(jobPercent({ progress: 1.2 }), 100)
  assert.equal(jobPercent({ progress: null }), null)
  assert.equal(jobPercent({}), null)
  assert.equal(isActiveJob({ status: 'running' }), true)
  assert.equal(isActiveJob({ status: 'done' }), false)
  assert.equal(KIND, 'model_import_tools')
})

test('not installed: the download and disk sizes, the sources, and Download', () => {
  const view = toolsView(status())
  assert.equal(view.state, 'not_installed')
  assert.equal(view.stateText, 'Not installed')
  assert.equal(view.downloadText, 'Download: about 791 MB')
  assert.equal(view.diskText, 'On disk: about 1.6 GB')
  // 0.9.0 build 3 smoke: "… and 11 more (PyPI (files.pythonhosted.org))". A source is never wrapped in more brackets.
  assert.deepEqual(view.sources, ['Blender 4.3.2 from download.blender.org', 'Python 3.13.17 from python.org',
    'bpy 5.2.2, numpy 2.5.3 and 11 more from PyPI (files.pythonhosted.org)'])
  assert.equal(sourceLines({ pieces: [{ name: 'python', label: 'Python 3.13.9', source: 'python-build-standalone (GitHub)' }] })[0],
    'Python 3.13.9 from python-build-standalone (GitHub)')
  assert.ok(view.sources.every(line => !/\([^)]*\(/.test(line)), 'no parentheses inside parentheses')
  assert.deepEqual(view.actions, { download: true, update: false, cancel: false, remove: false })
  assert.equal(view.downloadLabel, 'Download (791 MB)')
  assert.equal(view.path, null)
  assert.deepEqual(sourceLines({ pieces: [{ name: 'python', label: '', source: '' }, null] }), ['python'])
})

test('paused: a cancelled download says how much is in, and Resume fetches the rest; the sizes agree', () => {
  // 0.9.0 build 3 smoke: Cancel at 168 MB showed "Not installed", "Download (609 MB)" and "Download: about 779 MB".
  const view = toolsView(status({ state: 'paused', download_bytes: 779e6, needed_bytes: 611e6, downloaded_bytes: 168e6 }))
  assert.equal(view.state, 'paused')
  assert.equal(view.stateText, 'Paused · 168 of 779 MB')
  assert.equal(view.downloadText, 'Download: about 611 MB left of 779 MB')
  assert.equal(view.downloadLabel, 'Resume (611 MB)')
  assert.deepEqual(view.actions, { download: true, update: false, cancel: false, remove: false })
  assert.equal(view.percent, null)
  // A paused update: some pieces are installed, so Remove is there too; the part is of the update's own files.
  const update = toolsView(status({ state: 'paused', download_bytes: 791e6, needed_bytes: 300e6, downloaded_bytes: 100e6,
    pieces: PIECES.map(piece => ({ ...piece, installed: piece.name !== 'blender' })) }))
  assert.deepEqual([update.stateText, update.downloadText, update.downloadLabel, update.actions.remove],
    ['Paused · 100 of 400 MB', 'Download: about 300 MB left of 400 MB', 'Resume (300 MB)', true])
  // Paused with nothing on disk is not paused.
  assert.equal(toolsView(status({ state: 'paused', downloaded_bytes: 0 })).state, 'not_installed')
  // Resumed: the live job wins, as for any download.
  assert.equal(toolsView(status({ state: 'paused', downloaded_bytes: 168e6 }), { id: 'j', status: 'running', progress: 0.3 }).state,
    'downloading')
})

test('downloading: the live job wins over an older status, with its percent, its line and Cancel', () => {
  const job = { id: 'j1', kind: KIND, status: 'running', progress: 0.25, detail: 'Downloading Blender 4.3.2 (100 of 400 MB)' }
  const view = toolsView(status(), job)
  assert.equal(view.state, 'downloading')
  assert.equal(view.percent, 25)
  assert.equal(view.detail, 'Downloading Blender 4.3.2 (100 of 400 MB)')
  assert.equal(view.jobId, 'j1')
  assert.deepEqual(view.actions, { download: false, update: false, cancel: true, remove: false })
  // The status alone says a download runs (the job store has no record yet): still downloading.
  const fromStatus = toolsView(status({ state: 'downloading', job: { id: 'j2', status: 'queued', progress: null, detail: '' } }))
  assert.equal(fromStatus.state, 'downloading')
  assert.equal(fromStatus.percent, null)
  // An ended job in the store does not hold the card in downloading.
  assert.equal(toolsView(status({ state: 'installed', disk_estimated: false }), { id: 'j1', status: 'done' }).state, 'installed')
})

test('installed: measured size on disk, where they are, and Remove', () => {
  const view = toolsView(status({ state: 'installed', needed_bytes: 0, disk_bytes: 1.58e9, disk_estimated: false,
    pieces: PIECES.map(piece => ({ ...piece, installed: true })) }))
  assert.equal(view.stateText, 'Installed')
  assert.equal(view.diskText, 'On disk: 1.6 GB', 'measured, so no "about"')
  assert.equal(view.path, 'C:\\Data\\tools\\model-import')
  assert.deepEqual(view.actions, { download: false, update: false, cancel: false, remove: true })
})

test('update needed: only what changed is fetched, with Update and Remove', () => {
  const view = toolsView(status({ state: 'update_needed', needed_bytes: 380e6,
    pieces: PIECES.map(piece => ({ ...piece, installed: piece.name !== 'wheels' })) }))
  assert.equal(view.stateText, 'Update needed')
  assert.equal(view.downloadText, 'Download: about 380 MB of 791 MB')
  assert.equal(view.updateLabel, 'Update (380 MB)')
  assert.deepEqual(view.actions, { download: false, update: true, cancel: false, remove: true })
})

test('failed: the error in words, Try again, and Remove only when something is installed', () => {
  const view = toolsView(status({ state: 'failed', error: 'Not enough free space: the tools need about 1.9 GB and 0.4 GB is free.' }))
  assert.equal(view.stateText, 'The download failed')
  assert.match(view.error, /Not enough free space/)
  assert.equal(view.downloadLabel, 'Try again')
  assert.deepEqual(view.actions, { download: true, update: false, cancel: false, remove: false })
  const partly = toolsView(status({ state: 'failed', error: null, pieces: [{ ...PIECES[0], installed: true }] }))
  assert.equal(partly.error, 'It stopped before it finished.')
  assert.equal(partly.actions.remove, true)
  assert.equal(toolsView(status(), null, 'Another download is running.').requestError, 'Another download is running.')
})

test('not available on this computer, and loading', () => {
  const view = toolsView(status({ platform: 'linux-arm64', supported: false, state: 'unsupported', pieces: [],
    download_bytes: 0, needed_bytes: 0, disk_bytes: 0 }))
  assert.equal(view.stateText, 'Not available on this computer')
  assert.deepEqual(view.actions, { download: false, update: false, cancel: false, remove: false })
  assert.equal(view.downloadText, null)
  const loading = toolsView(null)
  assert.equal(loading.state, 'loading')
  assert.deepEqual(loading.actions, { download: false, update: false, cancel: false, remove: false })
})

test('an import that needs the tools: the reply\'s own size until the live status is known', () => {
  const reply = { status: 'needs_tools', warning: 'x', tools: { state: 'not_installed', download_bytes: 791e6,
    needed_bytes: 791e6, disk_bytes: 1.62e9 } }
  const need = importToolsNeed(reply)
  assert.deepEqual(need, { state: 'not_installed', neededBytes: 791e6, downloadBytes: 791e6, diskBytes: 1.62e9 })
  assert.equal(importToolsNeed({ status: 'done' }), null)
  const before = chatToolsView(need)
  assert.equal(before.state, 'not_installed')
  assert.equal(before.canStart, true)
  assert.equal(before.startLabel, 'Download the tools (about 791 MB)')
  assert.match(before.note, /Settings, under AI/)
  const update = chatToolsView(importToolsNeed({ ...reply, tools: { state: 'update_needed', needed_bytes: 380e6 } }))
  assert.equal(update.startLabel, 'Update the tools (about 380 MB)')
  const running = chatToolsView(need, status(), { id: 'j', status: 'running', progress: 0.5, detail: 'Unpacking Blender' })
  assert.deepEqual([running.state, running.percent, running.canStart, running.canCancel, running.note],
    ['downloading', 50, false, true, null])
  const installed = chatToolsView(need, status({ state: 'installed', disk_estimated: false }))
  assert.equal(installed.canStart, false)
  assert.equal(installed.note, 'The tools are installed. Ask Randall to import it again.')
  const failed = chatToolsView(need, status({ state: 'failed', error: 'The download of Blender did not match its checksum.' }))
  assert.deepEqual([failed.startLabel, failed.error], ['Try the download again (about 791 MB)',
    'The download of Blender did not match its checksum.'])
  // Cancelled part way (here or in Settings): paused, with what is in, and the button resumes it.
  const paused = chatToolsView(need, status({ state: 'paused', download_bytes: 779e6, needed_bytes: 611e6, downloaded_bytes: 168e6 }))
  assert.deepEqual([paused.state, paused.statusText, paused.canStart, paused.canCancel, paused.startLabel],
    ['paused', 'Paused · 168 of 779 MB', true, false, 'Resume the download (about 611 MB)'])
  assert.equal(before.statusText, null)
})
