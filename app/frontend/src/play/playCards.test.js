import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CPU_MESSAGE, NUCLEUS_IN_DOLPHIN, addingCard, bannerFit, cardLine, cardState, clientUpdate, coverKind, engineNote,
  gameSettingsNote, installLine, percent, pickTarget, replacedEntry, targetChoices,
} from './playCards.js'

const retail = {
  id: 'retail', name: 'Nucleus Unlocked', description: 'Mods, online lobbies and training, built in.', builtin: true,
  engine: 'source', defaultTarget: 'mu', hasCover: false,
  targets: { mu: { available: true }, dolphin: { available: true } },
}
const vanilla = {
  id: 'vanilla', name: 'Vanilla', description: 'Melee with nothing changed.', builtin: true, hasCover: true,
  engine: 'source', defaultTarget: 'mu', options: { vanilla: true },
  targets: { mu: { available: true }, dolphin: { available: false, reason: 'Vanilla runs on Melee Unlocked only.' } },
}
const ready = {
  platform: { supported: true }, retailIso: { set: true }, slippiPath: 'C:\\Slippi',
  client: { set: true, valid: true, engines: { source: true, compat: true } },
}
const job = (fields) => ({ id: 'j', kind: 'play_launch', status: 'running', params: { entryId: 'retail' }, extra: {}, ...fields })
// An added game, and the installed client's states (play/managed.py status, the play_client_install job).
const added = { id: 'abcdefabcdef', name: 'PokeMelee', builtin: false, engine: 'source', defaultTarget: 'mu',
  targets: { mu: { available: true }, dolphin: { available: true } } }
const none = { ...ready, client: { set: false, source: null, valid: false, error: null, folder: '' } }
const offer = { version: '1.0.8', size: 312 * 1024 * 1024, minAppVersion: '0.9.3', appTooOld: false }
const installJobRecord = (progress, fields = {}) => ({ id: 'i1', kind: 'play_client_install', status: 'running',
  progress, detail: 'Downloading 131 of 312 MB', params: { action: 'install' }, extra: { phase: 'downloading' }, ...fields })
const installed = { ...ready, client: { set: true, source: 'managed', valid: true, folder: 'C:\\x' } }

test('a card with everything set up is ready', () => {
  assert.deepEqual(cardState({ entry: retail, env: ready }),
    { state: 'ready', label: 'Play', reason: null, canPlay: true, target: 'mu', action: 'play', progress: null })
})

test('not on Windows', () => {
  const s = cardState({ entry: retail, env: { ...ready, platform: { supported: false, message: 'Nucleus Unlocked is Windows only for now.' } } })
  assert.equal(s.state, 'unsupported')
  assert.equal(s.reason, 'Nucleus Unlocked is Windows only for now.')
  assert.equal(s.canPlay, false)
})

test('needs your ISO', () => {
  const s = cardState({ entry: retail, env: { ...ready, retailIso: { set: false } } })
  assert.equal(s.state, 'needs-iso')
  assert.equal(s.reason, 'Nucleus Unlocked needs your Melee ISO. Choose it in Settings, Setup.')
  // A recorded disc whose file is gone (moved, renamed, a drive not connected) is named.
  const gone = 'C:\\Games\\Melee.iso'
  for (const entry of [retail, vanilla]) {
    const m = cardState({ entry, env: { ...installed, retailIso: { set: false, missing: gone } } })
    assert.deepEqual([m.state, m.canPlay], ['needs-iso', false])
    assert.equal(m.reason, 'Your Melee ISO was not found at C:\\Games\\Melee.iso. Choose it in Settings, Setup.')
  }
})

test('client not set, or set and broken', () => {
  // No client: the built-in cards install it; an added game says where to get it.
  let s = cardState({ entry: retail, env: { ...ready, client: { set: false, valid: false } } })
  assert.deepEqual([s.state, s.label, s.action, s.canPlay], ['install', 'Install', 'install', false])
  s = cardState({ entry: added, env: { ...ready, client: { set: false, valid: false } } })
  assert.deepEqual([s.state, s.action, s.reason], ['no-client', null, 'Install Nucleus Unlocked from its card first.'])
  // A hand-picked folder (the developer option) that broke says why.
  s = cardState({ entry: retail, env: { ...ready, client: { set: true, source: 'folder', valid: false, error: 'it has no melee_game.dll' } } })
  assert.equal(s.state, 'no-client')
  assert.match(s.reason, /own client folder can't be used: it has no melee_game\.dll/)
  // Dolphin does not need the client (an added game; the built-in cards never start Dolphin).
  s = cardState({ entry: added, env: { ...ready, client: { set: false } }, target: 'dolphin' })
  assert.equal(s.state, 'ready')
  s = cardState({ entry: retail, env: { ...ready, client: { set: false } }, target: 'dolphin' })
  assert.deepEqual([s.state, s.target], ['install', 'mu'])
})

// ---------------------------------------------------------------- the installed client (play/managed.py)

test('no client: Install says what it downloads, on both built-in cards, whatever else is missing', () => {
  const env = { ...none, retailIso: { set: false }, managed: { state: 'not_installed', available: offer } }
  for (const entry of [retail, vanilla]) {
    const s = cardState({ entry, env })
    assert.deepEqual([s.state, s.label, s.action], ['install', 'Install', 'install'])
    assert.equal(s.reason, 'Nucleus Unlocked is not installed yet. Install downloads it (312 MB).')
  }
  // The feed not read yet: no size.
  assert.equal(cardState({ entry: retail, env: { ...none, managed: null } }).reason,
    'Nucleus Unlocked is not installed yet. Install downloads it.')
})

test('installing shows the percent on the button and the step under it; added games wait', () => {
  let s = cardState({ entry: retail, env: { ...none, install: installJobRecord(0.42) } })
  assert.deepEqual([s.state, s.label, s.action, s.canPlay, s.progress], ['installing', 'Installing 42%', null, false, 0.42])
  assert.equal(s.reason, 'Downloading 131 of 312 MB')
  assert.equal(cardState({ entry: vanilla, env: { ...none, install: installJobRecord(0.999) } }).label, 'Installing 99%')
  assert.equal(cardState({ entry: retail, env: { ...none, install: installJobRecord(0) } }).label, 'Installing...')
  // Only the shelf answer knows (the job store has not caught up): the same.
  s = cardState({ entry: retail, env: { ...none, managed: { state: 'installing', job: { id: 'i1', action: 'install', progress: 0.5, detail: 'Unpacking' } } } })
  assert.deepEqual([s.state, s.label, s.reason], ['installing', 'Installing 50%', 'Unpacking'])
  // An ended job the shelf answer still names is not running.
  s = cardState({ entry: retail, env: { ...none, install: { ...installJobRecord(1), status: 'done' },
    managed: { state: 'installing', job: { id: 'i1', action: 'install', progress: 0.95 } } } })
  assert.equal(s.state, 'install')
  s = cardState({ entry: added, env: { ...none, install: installJobRecord(0.3) } })
  assert.deepEqual([s.state, s.canPlay], ['no-client', false])
})

test('a failed install says why in plain words and offers Install again', () => {
  const env = { ...none, managed: { state: 'failed', error: 'The download is not the one the client feed names (its SHA-256 differs). Nothing was installed.' } }
  const s = cardState({ entry: retail, env })
  assert.deepEqual([s.state, s.label, s.action], ['install-failed', 'Install', 'install'])
  assert.match(s.reason, /SHA-256 differs/)
  // An app older than the client needs: no Install, say so.
  const old = cardState({ entry: retail, env: { ...none, managed: { state: 'not_installed', available: { ...offer, appTooOld: true } } } })
  assert.deepEqual([old.state, old.action], ['unavailable', null])
  assert.equal(old.reason, 'This Nucleus Unlocked needs SSBM Nucleus 0.9.3 or newer. Update the app first.')
})

test('installed: Play; an installed client that broke offers Install again on the built-in cards', () => {
  assert.equal(cardState({ entry: retail, env: installed }).state, 'ready')
  const broken = { ...ready, client: { set: true, source: 'managed', valid: false, error: "The installed Nucleus Unlocked can't be used: it has no melee_game.dll Install it again from its card." } }
  let s = cardState({ entry: retail, env: broken })
  assert.deepEqual([s.state, s.action], ['install-failed', 'install'])
  assert.match(s.reason, /Install it again/)
  s = cardState({ entry: added, env: broken })
  assert.deepEqual([s.state, s.action], ['no-client', null])
})

test('an update is a quiet line on the built-in cards that never stops Play', () => {
  const env = { ...installed, managed: { state: 'installed', updateAvailable: true, available: offer } }
  assert.equal(cardState({ entry: retail, env }).state, 'ready')
  assert.deepEqual(clientUpdate({ entry: retail, env }), { label: 'Update to 1.0.8', busy: false, progress: null, detail: null })
  assert.equal(clientUpdate({ entry: vanilla, env }).label, 'Update to 1.0.8')
  assert.equal(clientUpdate({ entry: added, env }), null)
  // Updating: Play stays available, the line shows the percent.
  const updating = { ...env, install: installJobRecord(0.42, { params: { action: 'update' } }) }
  assert.deepEqual([cardState({ entry: retail, env: updating }).state, cardState({ entry: retail, env: updating }).canPlay], ['ready', true])
  assert.equal(clientUpdate({ entry: retail, env: updating }).label, 'Updating 42%')
  assert.equal(clientUpdate({ entry: retail, env: updating }).busy, true)
  // Nothing newer, an app too old for it, or a hand-picked folder in use: no line.
  assert.equal(clientUpdate({ entry: retail, env: { ...env, managed: { ...env.managed, updateAvailable: false } } }), null)
  assert.equal(clientUpdate({ entry: retail, env: { ...env, managed: { ...env.managed, available: { ...offer, appTooOld: true } } } }), null)
  assert.equal(clientUpdate({ entry: retail, env: { ...env, client: { ...env.client, source: 'folder' } } }), null)
})

test('percent never reads 100 before the end, and never below 0', () => {
  assert.deepEqual([0, 0.004, 0.42, 0.999, 1, -1, null, 'x'].map(percent), [0, 0, 42, 99, 99, 0, 0, 0])
  assert.equal(installLine({ size: 0 }), 'Nucleus Unlocked is not installed yet. Install downloads it.')
})

test('a processor Melee Unlocked cannot run on leaves Dolphin', () => {
  const env = { ...ready, client: { ...ready.client, cpuSupported: false, cpuBaseline: 'AVX2' } }
  let s = cardState({ entry: retail, env })
  assert.equal(s.state, 'unavailable')
  assert.equal(s.reason, CPU_MESSAGE)
  assert.equal(s.canPlay, false)
  s = cardState({ entry: added, env, target: 'dolphin' })
  assert.equal(s.state, 'ready')
  // Facts not known (an older answer, or none yet): nothing is held back.
  s = cardState({ entry: retail, env: { ...ready, client: { ...ready.client, cpuSupported: null } } })
  assert.equal(s.state, 'ready')
})

test('launching, then running, only on the card that was started', () => {
  let s = cardState({ entry: retail, env: ready, active: job({ detail: 'Checking your Melee disc...', extra: { phase: 'launching' } }) })
  assert.equal(s.state, 'launching')
  assert.equal(s.reason, 'Checking your Melee disc...')
  s = cardState({ entry: retail, env: ready, active: job({ extra: { phase: 'running', pid: 4 } }) })
  assert.deepEqual([s.state, s.canPlay], ['running', false])
  s = cardState({ entry: vanilla, env: ready, active: job({ extra: { phase: 'running' } }) })
  assert.deepEqual([s.state, s.reason, s.canPlay], ['busy', 'Another game is running.', false])
  s = cardState({ entry: vanilla, env: ready, active: job({ params: { entryId: null, settingsWindow: true } }) })
  assert.equal(s.reason, 'The game settings window is open.')
})

test('crashed, and other bad endings, say so and can play again', () => {
  const crashed = job({ status: 'done', result: { outcome: 'crashed', message: 'The game crashed. Its crash report is in its data folder.' } })
  let s = cardState({ entry: retail, env: ready, last: crashed })
  assert.deepEqual([s.state, s.label, s.canPlay], ['crashed', 'Play again', true])
  assert.match(s.reason, /crash report/)
  s = cardState({ entry: retail, env: ready, last: job({ status: 'done', result: { outcome: 'refused', message: 'The game refused to start this disc.' } }) })
  assert.deepEqual([s.state, s.reason], ['error', 'The game refused to start this disc.'])
  for (const outcome of ['fatal', 'cpu', 'disc_error', 'stopped']) {
    s = cardState({ entry: retail, env: ready, last: job({ status: 'done', result: { outcome, message: `said: ${outcome}` } }) })
    assert.deepEqual([s.state, s.reason, s.canPlay], ['error', `said: ${outcome}`, true])
  }
  s = cardState({ entry: retail, env: ready, last: job({ status: 'failed', error: "Your Melee ISO can't be used." }) })
  assert.deepEqual([s.state, s.reason], ['error', "Your Melee ISO can't be used."])
  // A normal quit leaves the card ready; another entry's crash is not this card's.
  s = cardState({ entry: retail, env: ready, last: job({ status: 'done', result: { outcome: 'quit' } }) })
  assert.equal(s.state, 'ready')
  s = cardState({ entry: vanilla, env: ready, last: crashed })
  assert.equal(s.state, 'ready')
})

test('a target that is not available says why', () => {
  const game = { ...added, targets: { mu: { available: true }, dolphin: { available: false, reason: 'This game runs on Melee Unlocked only.' } } }
  const s = cardState({ entry: game, env: ready, target: 'dolphin' })
  assert.deepEqual([s.state, s.reason], ['unavailable', 'This game runs on Melee Unlocked only.'])
  const noSlippi = cardState({ entry: added, env: { ...ready, slippiPath: '' }, target: 'dolphin' })
  assert.equal(noSlippi.state, 'unavailable')
  assert.match(noSlippi.reason, /Slippi Dolphin folder/)
})

test('the compatibility engine', () => {
  const entry = { ...retail, id: 'abcdefabcdef', builtin: false, engine: 'compat', engineReason: 'Runs on the compatibility engine (slower): 2 fighters have no native code.' }
  assert.equal(cardState({ entry, env: ready }).state, 'ready')
  const without = { ...ready, client: { ...ready.client, engines: { source: true, compat: false } } }
  assert.equal(cardState({ entry, env: without }).state, 'unavailable')
  assert.match(cardState({ entry, env: without }).reason, /Dolphin, or choose the Source Port/)
  assert.equal(cardState({ entry, env: without, target: 'dolphin' }).target, 'dolphin')
  assert.equal(engineNote(entry), entry.engineReason)
  assert.equal(engineNote(retail), null)
})

test('the target defaults to the last one used, and the chooser lists every target', () => {
  const game = { ...retail, id: '0123456789ab', builtin: false }
  assert.equal(pickTarget({ ...game, lastTarget: 'dolphin' }), 'dolphin')
  assert.equal(pickTarget(game, 'dolphin'), 'dolphin')
  // The built-in cards have no chooser: they start the client whatever was remembered.
  assert.equal(pickTarget({ ...retail, lastTarget: 'dolphin' }), 'mu')
  assert.equal(pickTarget(retail, 'dolphin'), 'mu')
  assert.equal(pickTarget(vanilla, 'switch'), 'mu')
  assert.deepEqual(targetChoices(vanilla), [
    { id: 'mu', label: 'Melee Unlocked', available: true, reason: null },
    { id: 'dolphin', label: 'Dolphin', available: false, reason: 'Vanilla runs on Melee Unlocked only.' },
  ])
  // On the Nucleus Unlocked card the Melee Unlocked target reads Nucleus Unlocked; its value, and Dolphin, stay.
  assert.deepEqual(targetChoices(retail).map((c) => [c.id, c.label]), [['mu', 'Nucleus Unlocked'], ['dolphin', 'Dolphin']])
  const added = { ...retail, id: '0123456789ab', builtin: false }
  assert.equal(targetChoices(added)[0].label, 'Melee Unlocked')
})

test("Vanilla's banner is drawn at the largest whole multiple of its pixels that fits, with room around it", () => {
  // The card picture at 1920 and 1440 wide windows (662 x 220), and at 960 (449 x 149).
  assert.deepEqual(bannerFit({ width: 662, height: 220 }), { scale: 5, width: 480, height: 160 })
  assert.deepEqual(bannerFit({ width: 449, height: 149 }), { scale: 3, width: 288, height: 96 })
  // Counted in device pixels: at 150% display scaling, 8 of them per banner pixel.
  const scaled = bannerFit({ width: 662, height: 220, dpr: 1.5 })
  assert.equal(scaled.scale, 8)
  assert.equal(Math.round(scaled.height * 1.5), 32 * 8)
  // A wide, short area is limited by its height, a narrow one by its width; never below 1x.
  assert.equal(bannerFit({ width: 2000, height: 104 }).scale, 2)
  assert.equal(bannerFit({ width: 232, height: 1000 }).scale, 2)
  assert.equal(bannerFit({ width: 0, height: 0 }).scale, 1)
})

test('a replay playing from Tracker keeps the cards busy and says so', () => {
  const s = cardState({ entry: retail, env: ready, active: job({ params: { entryId: null, replay: true } }) })
  assert.equal(s.state, 'busy')
  assert.equal(s.reason, 'A replay is playing in Nucleus Unlocked.')
})

test('the game settings line says where the settings came from, once', () => {
  assert.equal(gameSettingsNote(null), null)
  assert.equal(gameSettingsNote({ exists: true, seededAt: null, canSeed: false }), null)
  assert.match(gameSettingsNote({ exists: false, seededAt: null, canSeed: true }),
    /^The first game you start copies your Nucleus Unlocked folder's own settings/)
  assert.match(gameSettingsNote({ exists: true, seededAt: 1795000000, canSeed: false }),
    /^Copied once from your Nucleus Unlocked folder's own settings \(port-settings\.ini\) on .+\. Unlocked keeps its own copy/)
})

test('a game Nucleus found still running after a restart shows as playing, and its end as usual', () => {
  // play/launch.py reattach: a play_launch job of its own, marked reattached, phase running at once.
  const reattached = job({ params: { entryId: 'retail', target: 'mu', reattached: true }, extra: { phase: 'running', pid: 9 } })
  let s = cardState({ entry: retail, env: ready, active: reattached })
  assert.deepEqual([s.state, s.label, s.canPlay], ['running', 'Playing', false])
  s = cardState({ entry: vanilla, env: ready, active: reattached })
  assert.deepEqual([s.state, s.reason], ['busy', 'Another game is running.'])
  const ended = { ...reattached, status: 'done',
    result: { outcome: 'fatal', exitCode: 70, reattached: true, message: 'The game stopped on an error: x.' } }
  s = cardState({ entry: retail, env: ready, last: ended })
  assert.deepEqual([s.state, s.reason, s.canPlay], ['error', 'The game stopped on an error: x.', true])
  // Its exit code unknown (it ended between two looks): read as a quit, the card is ready.
  s = cardState({ entry: retail, env: ready, last: { ...ended, result: { outcome: 'quit', exitCode: null, reattached: true } } })
  assert.equal(s.state, 'ready')
})

test('the card of a game being added says Adding, or Replacing for a new version of one on the shelf', () => {
  assert.deepEqual(addingCard({ params: { artifactId: 'a', name: 'PokeMelee' }, detail: 'Linking the disc...' }),
    { name: 'PokeMelee', badge: 'Adding', detail: 'Linking the disc...' })
  assert.deepEqual(addingCard({ params: { patchId: 'p', name: 'PokeMelee', replace: '0123456789ab' } }),
    { name: 'PokeMelee', badge: 'Replacing', detail: 'Replacing...' })
  assert.deepEqual(addingCard({ params: {} }), { name: 'New game', badge: 'Adding', detail: 'Adding...' })
})

test('a finished replace asks for that game cover again; an add or a failure does not', () => {
  assert.equal(replacedEntry({ status: 'done', result: { entryId: '0123456789ab', replaced: true } }), '0123456789ab')
  assert.equal(replacedEntry({ status: 'done', result: { entryId: '0123456789ab', how: 'linked' } }), null)
  assert.equal(replacedEntry({ status: 'failed', result: null }), null)
  assert.equal(replacedEntry(null), null)
})

test('the line under a name is the description, except Nucleus played in Dolphin, which is only your disc', () => {
  assert.equal(cardLine(retail, 'mu'), 'Mods, online lobbies and training, built in.')
  assert.equal(cardLine(retail, 'dolphin'), NUCLEUS_IN_DOLPHIN)
  assert.equal(cardLine(vanilla, 'mu'), 'Melee with nothing changed.')
  const added = { id: '0123456789ab', name: 'Nucleus Unlocked', description: 'An export.', builtin: false }
  assert.equal(cardLine(added, 'dolphin'), 'An export.')          // only the built-in one is Nucleus Unlocked itself
  assert.equal(cardLine({ id: 'x' }, 'mu'), null)
})

test('pictures: Nucleus is drawn, Vanilla is the disc banner, an added game its cover or its name', () => {
  assert.equal(coverKind(retail), 'nucleus')
  assert.equal(coverKind(vanilla), 'banner')
  assert.equal(coverKind({ ...vanilla, hasCover: false }), 'plain')     // no disc yet
  assert.equal(coverKind({ id: '0123456789ab', builtin: false, hasCover: true }), 'picture')
  assert.equal(coverKind({ id: '0123456789ab', builtin: false, hasCover: false }), 'plain')
})
