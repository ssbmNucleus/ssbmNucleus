const monthGamesCache = new Map()

export function gamesForMonth(api, endpoint, month, revision = '') {
  const key = `${revision}:${month}`
  if (!monthGamesCache.has(key)) {
    const request = (async () => {
      const games = []
      let total = Infinity
      while (games.length < total) {
        const data = await api.get(endpoint, {
          query: { month, limit: 200, offset: games.length },
        })
        const page = data.games || []
        total = Number.isFinite(data.total) ? data.total : games.length + page.length
        games.push(...page)
        if (!page.length) break
      }
      return games
    })()
    monthGamesCache.set(key, request.catch((error) => {
      monthGamesCache.delete(key)
      throw error
    }))
  }
  return monthGamesCache.get(key)
}

export function clearMonthGamesCache() {
  monthGamesCache.clear()
}
