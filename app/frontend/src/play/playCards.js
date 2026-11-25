/**
 * playCards.js - what a shelf card shows, from what Play knows (pure, no React).
 *
 *   cardState({ entry, env, active, last, target })
 *     -> { state, label, reason, canPlay, target, action, progress }
 *
 * entry   one entry of GET /api/play/shelf
 * env     { platform, client, managed, install, retailIso: {set, missing}, slippiPath } from the same answer
 *         (managed: the installed Nucleus game client, play/managed.py status; install: the
 *         running play_client_install job as the job store has it, or null; slippiPath: the
 *         Slippi Dolphin folder the frontend keeps, for the Dolphin target)
 * active  the running play_launch job record, of any entry (or null)
 * last    the newest ended play_launch job record of this entry (or null)
 * target  the target picked on the card ('mu' or 'dolphin'); defaults to the entry's last
 *
 * States, most pressing first: unsupported, launching, running, install (no client yet: the
 * built-in cards' button installs it), installing, install-failed, needs-iso, unavailable,
 * no-client, busy (another game runs), crashed, error (the last start went wrong), ready.
 * `reason` is the one plain line under the card, saying what to do when something is missing.
 * `action` is what the primary button does: 'play', 'install' or nothing (null).
 *
 *   clientUpdate({ entry, env })  the quiet "Update" beside Play on the built-in cards, or null
 *
 *   cardLine(entry, target)  the line under the name     coverKind(entry)  which picture it shows
 *   bannerFit(area)          how big Vanilla's disc banner is drawn (whole pixels)
 */

export const TARGET_LABELS = { mu: 'Melee Unlocked', dolphin: 'Dolphin' }

// The two built-in games (play/shelf.py BUILTINS). 'retail' is the one named Nucleus Unlocked: the Melee
// Unlocked folder's client with everything it has. 'vanilla' is the same client with --vanilla-only.
export const NUCLEUS_ID = 'retail'
export const VANILLA_ID = 'vanilla'

// The Nucleus game with Dolphin chosen boots the user's own disc in their Slippi Dolphin, nothing more.
export const NUCLEUS_IN_DOLPHIN = 'Your own disc in Slippi Dolphin.'

/** The one line under a card's name: the entry's description, unless that would not be true for the target. */
export function cardLine(entry, target) {
  if (entry?.builtin && entry.id === NUCLEUS_ID && target === 'dolphin') return NUCLEUS_IN_DOLPHIN
  return entry?.description || null
}

/**
 * Which picture a card shows: 'nucleus' (the built-in Nucleus game: drawn from the app's own logo and
 * wordmark), 'banner' (the built-in Vanilla game: the user's disc banner, pixel art), 'picture' (an
 * added game's cover) or 'plain' (none: the name on a plain panel).
 */
export function coverKind(entry) {
  if (entry?.builtin && entry.id === NUCLEUS_ID) return 'nucleus'
  if (!entry?.hasCover) return 'plain'
  return entry.builtin && entry.id === VANILLA_ID ? 'banner' : 'picture'
}

// How a session ended badly (play/launch.py describe_exit); its message says why in words.
const ENDED_BADLY = new Set(['disc_error', 'refused', 'fatal', 'cpu', 'stopped'])

// What the Nucleus client says it needs (client.cpuSupported false: --print-info, play/launch.py CPU_MESSAGE).
export const CPU_MESSAGE = "This computer's processor cannot run Nucleus Unlocked: it needs a processor with AVX2. Play it in Dolphin instead."

// No disc to start (play/launch.py no_iso_message): where the recorded one was, when its file is gone.
export function needsIsoReason(retailIso) {
  return retailIso?.missing
    ? `Your Melee ISO was not found at ${retailIso.missing}. Choose it in Settings, Setup.`
    : 'Nucleus Unlocked needs your Melee ISO. Choose it in Settings, Setup.'
}

export function pickTarget(entry, target) {
  const targets = entry?.targets || {}
  // The two built-in cards have no chooser (EntryActions TargetChooser): they start the Nucleus
  // client, whatever was remembered from when they had one.
  const wanted = isBuiltin(entry) ? [] : [target, entry?.lastTarget, entry?.defaultTarget]
  for (const choice of [...wanted, 'mu', 'dolphin']) {
    if (choice && targets[choice]) return choice
  }
  return 'mu'
}

/**
 * The targets a card's chooser offers: [{ id, label, available, reason }]. On the built-in Nucleus
 * card the Melee Unlocked target is labeled Nucleus Unlocked, the game it starts there (the value stays 'mu').
 */
export function targetChoices(entry) {
  const nucleus = entry?.builtin && entry.id === NUCLEUS_ID
  return Object.entries(entry?.targets || {}).map(([id, info]) => ({
    id,
    label: nucleus && id === 'mu' ? 'Nucleus Unlocked' : TARGET_LABELS[id] || id,
    available: !!info?.available,
    reason: info?.reason || null,
  }))
}

// The disc banner's own size (play/adding.py BANNER_WIDTH, BANNER_HEIGHT) and the room kept around
// it, in CSS pixels, inside the card's picture.
export const BANNER_SIZE = { width: 96, height: 32 }
export const BANNER_PAD = 20

/**
 * How big Vanilla's disc banner is drawn in a picture area of `width` x `height` CSS pixels: the
 * largest whole multiple of its 96x32 pixels that leaves `pad` on every side, counted in device
 * pixels (`dpr`) so every banner pixel comes out the same size on any display scaling. Never below
 * 1x. -> { scale, width, height } (width and height in CSS pixels).
 */
export function bannerFit({ width, height, dpr = 1, pad = BANNER_PAD }) {
  const room = (length, unit) => Math.floor(((length - 2 * pad) * dpr) / unit + 1e-6)
  const scale = Math.max(1, Math.min(room(width, BANNER_SIZE.width), room(height, BANNER_SIZE.height)))
  return { scale, width: (BANNER_SIZE.width * scale) / dpr, height: (BANNER_SIZE.height * scale) / dpr }
}

function isActive(job) {
  return !!job && (job.status === 'queued' || job.status === 'running')
}

// The job that installs or updates the game client (play/managed.py KIND).
export const INSTALL_KIND = 'play_client_install'

/** The built-in games run the installed client and offer to install it. */
export function isBuiltin(entry) {
  return !!entry?.builtin && (entry.id === NUCLEUS_ID || entry.id === VANILLA_ID)
}

/** A progress fraction as the whole percent a button shows: 0.42 -> 42 (never 100 before the end). */
export function percent(fraction) {
  const value = Number(fraction)
  if (!Number.isFinite(value) || value <= 0) return 0
  return Math.min(99, Math.floor(value * 100))
}

/**
 * The client install or update running now, or null: { action: 'install' | 'update', progress, detail }.
 * The job store's live record first (env.install), else what the last shelf answer said (managed.job).
 */
export function installJob(env = {}) {
  const live = env.install
  if (isActive(live)) {
    return { action: live.params?.action || 'install', progress: live.progress ?? 0, detail: live.detail || null }
  }
  const job = env.managed?.job
  if (job && !(live && live.id === job.id)) {
    return { action: job.action || 'install', progress: job.progress ?? 0, detail: job.detail || null }
  }
  return null
}

function megabytes(size) {
  return Number.isFinite(size) && size > 0 ? `${Math.max(1, Math.round(size / (1024 * 1024)))} MB` : null
}

/** The line under a built-in card with no client yet: what Install does. */
export function installLine(offer) {
  const size = megabytes(offer?.size)
  return size ? `Nucleus Unlocked is not installed yet. Install downloads it (${size}).`
    : 'Nucleus Unlocked is not installed yet. Install downloads it.'
}

export const APP_TOO_OLD = (offer) => `This Nucleus Unlocked needs SSBM Nucleus ${offer.minAppVersion} or newer. Update the app first.`

/**
 * The quiet update action on a built-in card while the installed client is in use: null, or
 * { label, busy, progress } (busy: an update is downloading; Play stays available all along).
 */
export function clientUpdate({ entry, env = {} }) {
  if (!isBuiltin(entry) || env.client?.source !== 'managed') return null
  const job = installJob(env)
  if (job) {
    const pct = percent(job.progress)
    return { label: pct ? `Updating ${pct}%` : 'Updating...', busy: true, progress: job.progress, detail: job.detail }
  }
  const managed = env.managed
  if (!managed?.updateAvailable || !managed.available || managed.available.appTooOld) return null
  return { label: `Update to ${managed.available.version}`, busy: false, progress: null, detail: null }
}

export function cardState({ entry, env = {}, active = null, last = null, target = null }) {
  const chosen = pickTarget(entry, target)
  const out = (state, label, reason, canPlay, { action = canPlay ? 'play' : null, progress = null } = {}) =>
    ({ state, label, reason, canPlay, target: chosen, action, progress })
  const { platform, client, retailIso, slippiPath } = env

  if (platform && platform.supported === false) {
    return out('unsupported', 'Play', platform.message || 'Nucleus Unlocked is Windows only for now.', false)
  }
  if (isActive(active) && active.params?.entryId === entry.id) {
    if (active.extra?.phase === 'running') {
      return out('running', 'Playing', 'Playing now. Close the game to play something else.', false)
    }
    return out('launching', 'Starting...', active.detail || 'Starting...', false)
  }
  // No client yet: the built-in cards install it (their button), whatever else is missing.
  const job = installJob(env)
  if (chosen === 'mu' && !client?.set) {
    if (job) {
      if (!isBuiltin(entry)) {
        return out('no-client', 'Play', 'Nucleus Unlocked is being installed. This game can start once it is done.', false)
      }
      const pct = percent(job.progress)
      return out('installing', pct ? `Installing ${pct}%` : 'Installing...', job.detail || 'Installing Nucleus Unlocked...',
        false, { progress: job.progress })
    }
    if (!isBuiltin(entry)) {
      return out('no-client', 'Play', 'Install Nucleus Unlocked from its card first.', false)
    }
    const managed = env.managed || {}
    if (managed.available?.appTooOld) {
      return out('unavailable', 'Install', APP_TOO_OLD(managed.available), false)
    }
    if (managed.state === 'failed' && managed.error) {
      return out('install-failed', 'Install', managed.error, false, { action: 'install' })
    }
    return out('install', 'Install', installLine(managed.available), false, { action: 'install' })
  }
  if (!retailIso?.set) {
    return out('needs-iso', 'Play', needsIsoReason(retailIso), false)
  }
  const info = entry.targets?.[chosen]
  if (!info?.available) {
    return out('unavailable', 'Play', info?.reason || 'This game cannot be played there.', false)
  }
  if (chosen === 'mu') {
    if (!client.valid) {
      if (client.source === 'managed') {
        // The installed client broke (files removed or changed): the built-in cards install it again.
        return isBuiltin(entry) && !job
          ? out('install-failed', 'Install', client.error || "The installed Nucleus Unlocked can't be used. Install it again.",
            false, { action: 'install' })
          : out('no-client', 'Play', client.error || "The installed Nucleus Unlocked can't be used.", false)
      }
      return out('no-client', 'Play', `Your own client folder can't be used: ${client.error || 'check it in Unlocked, Settings.'}`, false)
    }
    if (client.cpuSupported === false) {
      return out('unavailable', 'Play', CPU_MESSAGE, false)
    }
    if (!isBuiltin(entry) && entry.engine === 'compat' && client.engines && !client.engines.compat) {
      return out('unavailable', 'Play',
        'This game needs the compatibility engine (melee_port.exe), and your client does not have it. '
        + 'Play it in Dolphin, or choose the Source Port in its menu.', false)
    }
  }
  if (chosen === 'dolphin' && !slippiPath) {
    return out('unavailable', 'Play', 'Set your Slippi Dolphin folder in Settings, Setup to play in Dolphin.', false)
  }
  if (isActive(active)) {
    return out('busy', 'Play', active.params?.settingsWindow ? 'The game settings window is open.'
      : active.params?.replay ? 'A replay is playing in Nucleus Unlocked.' : 'Another game is running.', false)
  }
  if (last && last.params?.entryId === entry.id) {
    if (last.status === 'done' && last.result?.outcome === 'crashed') {
      return out('crashed', 'Play again', last.result.message || 'The game crashed.', true)
    }
    if (last.status === 'done' && ENDED_BADLY.has(last.result?.outcome)) {
      return out('error', 'Play', last.result.message, true)
    }
    if (last.status === 'failed') {
      return out('error', 'Play', last.error || 'The game could not start.', true)
    }
  }
  return out('ready', 'Play', null, true)
}

/**
 * What the card for a running shelf_add job says (AddingCard.jsx): { name, badge, detail }.
 * A job with params.replace builds a new version of a game already on the shelf (play/adding.py);
 * that game's own card stays as it is until the new one is ready.
 */
export function addingCard(job) {
  const name = job?.params?.name || 'New game'
  const replacing = Boolean(job?.params?.replace)
  return {
    name,
    badge: replacing ? 'Replacing' : 'Adding',
    detail: job?.detail || (replacing ? 'Replacing...' : 'Adding...'),
  }
}

/**
 * The entry whose cover an ended shelf_add job may have changed under the same address, or null:
 * a replace keeps the entry's id, so its card must ask for the cover again (PlayApp coverVersions).
 */
export function replacedEntry(job) {
  return job?.status === 'done' && job.result?.replaced && typeof job.result.entryId === 'string'
    ? job.result.entryId : null
}

/** The engine line on a card, when it is worth one ('Runs on the compatibility engine...'). */
export function engineNote(entry) {
  // The built-in games always run on the Source Port (play/launch.py): no engine line, no choice.
  if (isBuiltin(entry) || entry?.engine !== 'compat') return null
  return entry.engineReason || 'Runs on the compatibility engine (slower).'
}

/**
 * The line under "Game settings" about where Play's settings came from (GET /api/play/shelf gameSettings:
 * play/shelf.py game_settings_status). Play keeps one port-settings.ini of its own; the first game copies the
 * Nucleus client folder's own one into it, once. null when there is nothing to say.
 */
export function gameSettingsNote(gameSettings) {
  if (!gameSettings) return null
  if (gameSettings.seededAt) {
    const day = new Date(gameSettings.seededAt * 1000).toLocaleDateString()
    return `Copied once from your Nucleus Unlocked folder's own settings (port-settings.ini) on ${day}. `
      + 'Unlocked keeps its own copy: changes here do not change that folder.'
  }
  if (gameSettings.canSeed) {
    return "The first game you start copies your Nucleus Unlocked folder's own settings (port-settings.ini), once. "
      + 'After that Unlocked keeps its own copy.'
  }
  return null
}
