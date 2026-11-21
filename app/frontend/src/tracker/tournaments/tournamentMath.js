// Pure derivations for the "Your start.gg" tournaments panel: everything is
// computed from the player's own synced sets/standings (no extra API calls).

// The standard bracket-placement ladder: the distinct placements a double-elim
// bracket can produce (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, ...). Seeds and
// placements are only comparable as *tiers* on this ladder — beating seed 9
// as seed 13 is one tier, not four seeds. This is the same ladder behind the
// community's "upset factor".
const LADDER = (() => {
  const v = [1, 2, 3, 4, 5]
  let step = 2
  while (v[v.length - 1] < 100000) {
    v.push(v[v.length - 1] + step)
    v.push(v[v.length - 1] + step)
    step *= 2
  }
  return v
})()

/** Index of a seed/placement on the bracket ladder (0 = seed 1). */
export function seedTier(n) {
  if (n == null || n < 1) return null
  let i = 0
  while (i + 1 < LADDER.length && LADDER[i + 1] <= n) i += 1
  return i
}

/** Upset factor of a finished set: ladder distance between the seeds, positive
 * when the worse seed won. 0 when seeds are missing or same-tier. */
export function upsetFactor(winnerSeed, loserSeed) {
  const w = seedTier(winnerSeed)
  const l = seedTier(loserSeed)
  if (w == null || l == null) return 0
  return Math.max(0, w - l)
}

export function ordinal(n) {
  if (n == null) return '—'
  const rem10 = n % 10
  const rem100 = n % 100
  const suffix = rem100 >= 11 && rem100 <= 13 ? 'th'
    : rem10 === 1 ? 'st' : rem10 === 2 ? 'nd' : rem10 === 3 ? 'rd' : 'th'
  return `${n}${suffix}`
}

/** Ladder-tier delta between where you were seeded and where you placed:
 * positive = outperformed your seed, negative = underperformed. */
export function seedDelta(seed, placement) {
  const s = seedTier(seed)
  const p = seedTier(placement)
  if (s == null || p == null) return null
  return s - p
}

const DQ_SCORE = -1

/** Augment one raw proxy set with the player's perspective. Returns null when
 * the player isn't in the set (shouldn't happen for player.sets). */
function perspective(set, playerId) {
  const slots = set.slots || []
  if (slots.length !== 2) return null
  const mine = slots.find((sl) => (sl.player_ids || []).includes(playerId))
  const theirs = slots.find((sl) => sl !== mine)
  if (!mine || !theirs) return null
  const won = set.winner_id != null && set.winner_id === mine.entrant_id
  const dq = mine.score === DQ_SCORE || theirs.score === DQ_SCORE
  const uf = won ? upsetFactor(mine.seed, theirs.seed) : upsetFactor(theirs.seed, mine.seed)
  return {
    ...set,
    me: mine,
    opp: theirs,
    won,
    dq,
    // doubles: the "opponent" is a team name — fine inside an event run, but
    // kept out of head-to-head records and best-wins (they're singles stats)
    teams: (mine.player_ids || []).length > 1 || (theirs.player_ids || []).length > 1,
    // uf > 0 on a win = you upset them; on a loss = they upset you
    upset: won && !dq && uf > 0,
    gotUpset: !won && !dq && uf > 0,
    uf,
  }
}

/** Group the synced sets into events (tournament runs), newest first. */
export function groupEvents(sets, playerId) {
  if (!playerId) return []
  const byEvent = new Map()
  for (const raw of sets) {
    const set = perspective(raw, playerId)
    if (!set || !set.event?.id) continue
    let ev = byEvent.get(set.event.id)
    if (!ev) {
      ev = { key: set.event.id, event: set.event, sets: [] }
      byEvent.set(set.event.id, ev)
    }
    ev.sets.push(set)
  }
  const events = [...byEvent.values()]
  for (const ev of events) {
    ev.sets.sort((a, b) => (a.completed_at || 0) - (b.completed_at || 0))
    ev.lastAt = Math.max(ev.event.start_at || 0, ...ev.sets.map((s) => s.completed_at || 0))
    ev.seed = ev.sets.map((s) => s.me.seed).find((v) => v != null) ?? null
    // event-level final placement rides on the entrant standing of every slot
    ev.placement = ev.sets.map((s) => s.me.placement).find((v) => v != null) ?? null
    ev.wins = ev.sets.filter((s) => s.won && !s.dq).length
    ev.losses = ev.sets.filter((s) => !s.won && !s.dq).length
    ev.delta = seedDelta(ev.seed, ev.placement)
  }
  events.sort((a, b) => b.lastAt - a.lastAt)
  return events
}

/** Head-to-head records across every synced set, keyed by opponent. */
export function headToHead(events) {
  const byOpp = new Map()
  for (const ev of events) {
    for (const set of ev.sets) {
      if (set.dq || set.teams) continue
      const key = (set.opp.player_ids || [])[0] ?? `name:${set.opp.name}`
      let rec = byOpp.get(key)
      if (!rec) {
        rec = { key, name: set.opp.name, wins: 0, losses: 0, lastAt: 0, sets: [] }
        byOpp.set(key, rec)
      }
      if (set.won) rec.wins += 1
      else rec.losses += 1
      if ((set.completed_at || 0) >= rec.lastAt) {
        rec.lastAt = set.completed_at || 0
        rec.name = set.opp.name // latest tag they entered under
      }
      rec.sets.push(set)
    }
  }
  return [...byOpp.values()]
}

/** Opponents who own you: losing record over 2+ sets, worst first. */
export function demons(h2h) {
  return h2h
    .filter((r) => r.wins + r.losses >= 2 && r.losses > r.wins)
    .sort((a, b) => (b.losses - b.wins) - (a.losses - a.wins)
      || (b.losses + b.wins) - (a.losses + a.wins))
}

/** Your proudest scalps: won sets ranked by upset factor. */
export function bestWins(events, limit = 6) {
  const wins = []
  for (const ev of events) {
    for (const set of ev.sets) {
      if (set.won && !set.dq && !set.teams && set.uf > 0) wins.push({ ...set, eventInfo: ev.event })
    }
  }
  wins.sort((a, b) => b.uf - a.uf || (b.completed_at || 0) - (a.completed_at || 0))
  return wins.slice(0, limit)
}

/** Chronological seed-vs-placement series for the trajectory chart. */
export function trajectory(events) {
  return events
    .filter((ev) => ev.delta != null)
    .slice()
    .sort((a, b) => a.lastAt - b.lastAt)
}

/** Format a set score from the two slot scores ("3–1", "W" when unscored). */
export function scoreLabel(set) {
  if (set.dq) return 'DQ'
  if (set.me.score == null || set.opp.score == null) return set.won ? 'W' : 'L'
  return `${set.me.score}–${set.opp.score}`
}

// ── Local Slippi replay matching ──────────────────────────────────────────
// start.gg gives each set a completion timestamp; the local replay index gives
// each game a start time, duration, result, and (netplay) connect codes — with
// `user_port` already resolved against EVERY claimed code, not just the active
// login. Matching, per set in bracket order, from a shared pool:
//   1. candidate games end inside the set's window (completion −75 to +15 min)
//      and match the set's singles/doubles-ness;
//   2. candidates are grouped by opponent connect code (netplay tournaments:
//      every game of a set is vs ONE code) and the group whose recent W/L best
//      fits the reported set score wins;
//   3. only the last `score-total` games of that group are taken (a 3–1 set is
//      4 games, never the warmup friendlies before it), and taken games leave
//      the pool so they can't double-match a later set.
// Offline replays without codes fall back to time order, still score-capped.
// The window is generous on the early side — completed_at is when the score
// was REPORTED, and TOs report late — the score fit is what keeps precision.
const WINDOW_BEFORE_MS = 240 * 60 * 1000
const WINDOW_AFTER_MS = 45 * 60 * 1000
const FALLBACK_MAX_GAMES = 5 // no reported score -> at most a Bo5's worth
const MIN_REAL_GAME_S = 45   // shorter = false start / handwarmer quit

// Pick which of one opponent-group's games belong to this set. Real sets are
// CONTIGUOUS games vs that opponent, so first look for the run whose W/L
// exactly matches the reported score (nearest run to the report time wins) —
// this steps over 4-second quits, false starts, and pre/post friendlies.
function pickGames(list, s, setEnd, scored) {
  const total = scored ? s.me.score + s.opp.score : (s.total_games || FALLBACK_MAX_GAMES)
  if (!total) return null
  const clean = list.filter((c) => c.g.result && (c.g.duration_s || 0) >= MIN_REAL_GAME_S)
  if (scored && clean.length >= total) {
    let best = null
    for (let i = 0; i + total <= clean.length; i += 1) {
      const run = clean.slice(i, i + total)
      const wins = run.filter((c) => c.g.result === 'win').length
      if (wins !== s.me.score) continue
      const gap = Math.abs(setEnd - run[run.length - 1].end)
      if (!best || gap < best.gap) best = { run, gap }
    }
    if (best) return { take: best.run, penalty: (best.gap / 60000) * 0.2 }
  }
  // fallback: the last `total` plausible games, scored by W/L fit + time gap
  const pool = clean.length ? clean : list
  const take = pool.slice(-Math.min(total, pool.length))
  const wins = take.filter((c) => c.g.result === 'win').length
  const losses = take.filter((c) => c.g.result === 'loss').length
  const fit = scored
    ? Math.abs(wins - s.me.score) + Math.abs(losses - s.opp.score)
    : 0
  const gapMin = Math.abs(setEnd - take[take.length - 1].end) / 60000
  return { take, penalty: fit * 150 + gapMin * 0.2 }
}

function opponentKey(g) {
  const opps = (g.players || []).filter((p) => p.port !== g.user_port)
  const codes = opps.map((p) => (p.code || '').toUpperCase()).filter(Boolean).sort()
  return codes.join('+') // '' = offline / no codes
}

export function matchReplaysToSets(sets, games) {
  const out = new Map()
  const timed = sets
    .filter((s) => s.completed_at)
    .sort((a, b) => a.completed_at - b.completed_at)
  if (!timed.length) return out

  // pool: every game that is verifiably the player's (any claimed code)
  let pool = (games || [])
    .filter((g) => g.start_at && g.user_port != null)
    .map((g) => {
      const end = Date.parse(g.start_at) + (g.duration_s || 0) * 1000
      return Number.isNaN(end) ? null : { g, end, opp: opponentKey(g) }
    })
    .filter(Boolean)
    .sort((a, b) => a.end - b.end)

  for (const s of timed) {
    if (s.dq) continue // a DQ has no games; don't attach stray friendlies
    const setEnd = s.completed_at * 1000
    // (careful: null >= 0 is true in JS — unscored sets must fall through)
    const scored = Number.isInteger(s.me.score) && s.me.score >= 0
      && Number.isInteger(s.opp.score) && s.opp.score >= 0
    const total = scored ? s.me.score + s.opp.score
      : (s.total_games || FALLBACK_MAX_GAMES)
    const window = pool.filter((c) => c.end >= setEnd - WINDOW_BEFORE_MS
      && c.end <= setEnd + WINDOW_AFTER_MS
      && !!c.g.is_teams === !!s.teams)
    if (!window.length || !total) continue

    // group by opponent code; the codeless group only competes when no coded
    // group exists (an offline bracket on a laptop has no codes at all)
    const groups = new Map()
    for (const c of window) {
      if (!groups.has(c.opp)) groups.set(c.opp, [])
      groups.get(c.opp).push(c)
    }
    const coded = [...groups.entries()].filter(([key]) => key !== '')
    const candidates = coded.length ? coded : [...groups.entries()]

    let bestTake = null
    let bestPenalty = Infinity
    for (const [, list] of candidates) {
      const pick = pickGames(list, s, setEnd, scored)
      if (pick && pick.penalty < bestPenalty) {
        bestPenalty = pick.penalty
        bestTake = pick.take
      }
    }
    // a coded group that doesn't remotely fit the score is a different
    // opponent (friendlies) — don't attach it
    if (!bestTake || (scored && bestPenalty >= 380)) continue

    out.set(s.id, bestTake.map((c) => c.g))
    const taken = new Set(bestTake)
    pool = pool.filter((c) => !taken.has(c))
  }
  return out
}
