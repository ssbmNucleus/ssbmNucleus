// The header wordmark cycles the app's modes: Nucleus -> Tracker -> Unlocked (id 'play') -> Nucleus.
// The cycle skips Tracker when NUCLEOME_ENABLED is off and Unlocked when PLAY_ENABLED
// is off. Unlocked is in Windows stable builds since 0.10.0 and in Play test builds.

// What each mode is called on screen. The id 'play' is shown as Unlocked: its wordmark reads
// "SSBM Nucleus Unlocked", the game it installs and starts.
export const MODE_NAMES = { nucleus: 'Nucleus', nucleome: 'Tracker', play: 'Unlocked' }

export function modeCycle({ tracker = false, play = false } = {}) {
  return ['nucleus', ...(tracker ? ['nucleome'] : []), ...(play ? ['play'] : [])]
}

// The mode the app opens in. `stored` is the mode remembered from the last switch
// (localStorage, App.jsx), or null when none was ever remembered: a first run. A first run
// opens on Unlocked ('play') in a build that has it, since new players mostly come for the
// game, and on Nucleus otherwise. A remembered mode is kept; one this build leaves out, or
// anything unknown, falls back to Nucleus as before.
export function startingMode(stored, { tracker = false, play = false } = {}) {
  if (stored === null || stored === undefined || stored === '') return play ? 'play' : 'nucleus'
  if (play && stored === 'play') return 'play'
  return tracker && stored === 'nucleome' ? 'nucleome' : 'nucleus'
}

// The mode a click on the wordmark switches to. A mode that is not in the cycle (a
// stored mode this build left out) goes back to the first one, Nucleus.
export function nextMode(mode, cycle) {
  const at = cycle.indexOf(mode)
  return cycle[(at + 1) % cycle.length]
}
