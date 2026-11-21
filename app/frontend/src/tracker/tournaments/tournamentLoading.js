// Profile pictures and standings must not hold the latest run behind a full
// history sync. Every callback belongs to the currently requested slug/refresh.
export function createTournamentLoader({ cached, profile, standings, sets,
  onProfile, onStandings, onSets, onPhase }) {
  let current = null
  return {
    async load(slug, { force = false } = {}) {
      const token = {}
      current = token
      const accept = setter => value => { if (current === token) setter(value) }
      const saved = cached(slug)
      if (saved.profile) onProfile(saved.profile)
      if (saved.standings) onStandings(saved.standings)
      if (saved.sets) onSets(saved.sets)
      onPhase('loading')
      Promise.resolve().then(() => current === token ? profile(slug) : null).then(accept(onProfile)).catch(() => {})
      Promise.resolve().then(() => current === token ? standings(slug, { force }) : null).then(accept(onStandings))
        .catch(() => accept(onStandings)(null))
      try {
        const result = await sets(slug, { force, onProgress: accept(onSets) })
        if (current === token) { onSets(result); onPhase('ready') }
      } catch {
        if (current === token) onPhase('error')
      }
    },
    cancel() { current = null },
  }
}
