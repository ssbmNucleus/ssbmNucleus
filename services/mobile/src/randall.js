// Randall tab — the AI replay coach, on the phone. The inversion that makes
// this affordable: the phone already holds the ENTIRE library + combos in
// memory, so Randall's tools run RIGHT HERE in JS and only the model reasoning
// crosses the network. The chat loop lives in this file: send history + tool
// schemas -> the randall-chat edge function proxies ONE OpenRouter call on the
// owner's per-user key -> if the model asked for tools, run them locally over
// store data, append the results, call again (capped rounds per user message).
//
// Entitlement is resolved server-side; {error:"no_ai"} renders a Patreon
// upsell card, never an error toast. Replies that came from tool rows carry
// tappable game/combo chips that jump straight into the replay via openDetail.
import { charName, stageName, moveName } from '../../../app/frontend/src/shared/data/meleeNames'
import { compute } from './stats'
import { applyFilters } from './games'
import { getToken, chatsGet, chatsPut } from './api'
import { el, esc, toast, num, shortDate, stockSrc, sheet, sheetRow } from './ui'
import { openDetail } from './detail'
import { clipCard, clipReel } from './clipcard'
import { randallSvg } from '../../../app/frontend/src/tracker/replays/itemArt'
import {
  CONSENT_LINE, NOT_INCLUDED, buildMobileReport, describeReport, errorText, sendMobileReport, zipStore,
} from './chat-report'

const CFG = window.__VAULT || {}
const FN_CHAT = `${CFG.supabaseUrl}/functions/v1/randall-chat`

// The desktop's model list (coach_api.COACH_MODELS). The client sends the KEY
// and the edge function maps it — a model id from a phone is never trusted.
const MODELS = [
  { key: 'minimax', label: 'Minimax', sub: 'The default — fast, good with numbers' },
  { key: 'glm', label: 'GLM', sub: 'Wordier, strong at explaining why' },
  { key: 'deepseek', label: 'Deepseek', sub: 'Slower, more careful reasoning' },
]
const MODEL_KEY = 'nucleus.randall.model'

const MAX_ROUNDS = 6          // model calls per user message before forcing an answer
const MAX_API_MSGS = 40       // persisted history cap (whole leading turns dropped)
const STORE_KEY = 'nucleus.randall.chat'
const PATREON_URL = 'https://www.patreon.com/cw/ssbmSc00p/membership'

// ── persona ────────────────────────────────────────────────────────────────
// Adapted from the desktop coach's evaluated stats-only prompt
// (backend/randall/coach/coach_prompt.SYSTEM_PROMPT), cut down to the
// four phone tools. Hard rules preserved: stats-only, no invented numbers,
// no frame-data guessing, no playbook.
const SYSTEM_PROMPT = `You are Randall, the player's Melee coach and stats \
analyst inside the Nucleus vault app on their phone. You speak as Randall — \
never mention any underlying model or assistant.

Ground truth: everything you say about the player comes from your tools over \
their synced replay library. Never invent or estimate a number — if you \
didn't just read it from a tool this conversation, don't say it. Nothing \
about the player is baked into you: their characters, results, and history \
all come from the tools (start with get_overview in a fresh conversation). \
"My Falco" always means the character THE PLAYER plays, never the opponent.

Your tools: get_overview (record, winrate, matchups, stages, monthly trend, \
rivals, sessions, rage-quits — optionally sliced to one of the player's \
characters and/or a date range; slice two windows to answer "what changed"), \
list_games (find specific games), list_combos (the player's indexed combos \
with move sequences), head_to_head (the full record against one opponent). \
This is the phone app: you have game-level results and combos, not \
frame-mined execution stats — for L-cancel rates, death causes, and deep \
per-character work, point the player at Randall in the Nucleus desktop app.

How to answer:
- Lead with the player's real numbers, then what they mean, then one \
concrete thing to work on. One leak at a time — the biggest measured gap, \
not a laundry list.
- Weigh thin samples honestly: a 2-0 record is not a dominant matchup.
- If the player's question assumes something the data contradicts, say so \
directly — don't agree to be agreeable.
- You may reference specific games or combos your tools returned ("your \
Aug 3 loss to that Marth") — the app renders them under your reply as \
tappable cards, and combos play as clips right there, so name them naturally \
instead of dumping raw rows. Pulling a couple of relevant combos is worth it \
when the player asks about their offence: they get to watch what you mean.
- Never state specific frame data, percent windows, or kill-confirm \
thresholds unless you are certain it is a well-known MELEE fact; a made-up \
number presented confidently is worse than no number.
- No generic advice ("DI better", "practice more") — every recommendation \
anchors to a number or matchup you actually pulled this conversation.
- Plain English, never raw stat keys. Be concise — this is a phone screen: \
short paragraphs, no giant tables.`

// ── tool schemas (sent with every model call — kept tight, the model pays) ──
const TOOL_SCHEMAS = [
  {
    type: 'function',
    function: {
      name: 'get_overview',
      description: 'Aggregate stats over the synced library: record, winrate, playtime, matchups, stages, monthly activity, rivals, sessions, rage-quits. Optionally sliced to one of the player\'s characters and/or a date range.',
      parameters: {
        type: 'object',
        properties: {
          my_char: { type: 'string', description: "player's character name, e.g. 'Falco'" },
          start: { type: 'string', description: 'YYYY-MM-DD, inclusive' },
          end: { type: 'string', description: 'YYYY-MM-DD, inclusive' },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'list_games',
      description: 'Find specific games. Returns compact rows (date, characters, codes, result, stage, stocks left).',
      parameters: {
        type: 'object',
        properties: {
          my_char: { type: 'string', description: "player's character name" },
          opp_char: { type: 'string', description: "opponent's character name" },
          opp: { type: 'string', description: 'opponent name or connect-code substring' },
          stage: { type: 'string', description: "stage name, e.g. 'Battlefield'" },
          result: { type: 'string', enum: ['win', 'loss'] },
          limit: { type: 'integer', description: 'max rows, <= 20 (default 10)' },
          newest_first: { type: 'boolean', description: 'default true' },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'list_combos',
      description: "The player's indexed combos, biggest damage first: move sequence, damage, percent range, kill flag, opponent.",
      parameters: {
        type: 'object',
        properties: {
          character: { type: 'string', description: "player's character name" },
          min_damage: { type: 'number', description: 'minimum combo damage %' },
          kills_only: { type: 'boolean' },
          limit: { type: 'integer', description: 'max rows, <= 15 (default 8)' },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'head_to_head',
      description: 'Full record against one opponent (name or connect-code substring): W-L, per-character breakdown, most recent games.',
      parameters: {
        type: 'object',
        properties: {
          opponent: { type: 'string', description: 'opponent name or connect-code substring' },
        },
        required: ['opponent'],
        additionalProperties: false,
      },
    },
  },
]

const TOOL_LABELS = {
  get_overview: 'crunching your stats…',
  list_games: 'pulling up games…',
  list_combos: 'digging through combos…',
  head_to_head: 'checking the head-to-head…',
}

const STARTERS = [
  "How's my Falco doing this month?",
  "Who's my worst matchup?",
  'Show me my best combos',
]

// ── name resolution (the model speaks names, the library speaks ids) ───────
const CHAR_IDS = (() => {
  const m = new Map()
  for (let i = 0; i < 26; i++) m.set(String(charName(i)).toLowerCase(), i)
  return m
})()
const STAGE_IDS = (() => {
  const m = new Map()
  for (const s of [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
    19, 20, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32]) {
    m.set(String(stageName(s)).toLowerCase(), s)
  }
  return m
})()

function resolveIn(map, name) {
  if (name == null || name === '') return ''
  const s = String(name).trim().toLowerCase()
  if (/^\d+$/.test(s)) return s
  if (map.has(s)) return String(map.get(s))
  for (const [k, v] of map) {
    if (k.includes(s) || s.includes(k)) return String(v)
  }
  return ''
}
const resolveChar = (n) => resolveIn(CHAR_IDS, n)
const resolveStage = (n) => resolveIn(STAGE_IDS, n)

const wr = (x) => (x == null ? null : Math.round(x * 1000) / 10)
const me = (g) => (g.user_port != null
  ? (g.players || []).find((p) => p.port === g.user_port) : null)
const opps = (g) => (g.user_port != null
  ? (g.players || []).filter((p) => p.port !== g.user_port)
  : (g.players || []).slice(1))

// ── the tools (LEAN results — the model pays tokens for every byte) ────────

function gameRow(g, chips) {
  const m = me(g)
  const o = opps(g)[0]
  const st = g.end_stocks || {}
  const label = `${charName(m?.character)} vs ${charName(o?.character)} · ${shortDate(g.start_at)}`
  chips.push({ hash: g.content_hash, label, icon: o?.character })
  return {
    date: (g.start_at || '').slice(0, 10),
    me: charName(m?.character),
    opp: charName(o?.character),
    opp_name: o?.name || null,
    opp_code: o?.code || null,
    stage: stageName(g.stage),
    result: g.result || 'unknown',
    stocks: `${st[String(m?.port)] ?? '?'}-${st[String(o?.port)] ?? '?'}`,
    dur_s: g.duration_s || null,
  }
}

function toolGetOverview(store, args) {
  const f = {
    myChar: resolveChar(args.my_char),
    start: args.start || '',
    end: args.end || '',
  }
  const s = compute(store.games, f)
  const o = s.overview
  return {
    sliced_to: {
      character: f.myChar !== '' ? charName(Number(f.myChar)) : 'all',
      start: f.start || null,
      end: f.end || null,
    },
    record: {
      games: o.games,
      wins: o.wins,
      losses: o.losses,
      winrate_pct: wr(o.winrate),
      unscored: o.games - o.wins - o.losses,
    },
    playtime_hours: Math.round((o.playtime_s / 3600) * 10) / 10,
    opponents: o.opponents,
    active_days: o.active_days,
    sessions: {
      count: s.sessions.count,
      avg_games: s.sessions.avg_games,
      longest: s.sessions.longest,
    },
    matchups: s.matchups.slice(0, 8).map((e) => ({
      vs: charName(e.key), games: e.games, w: e.wins, l: e.losses, wr_pct: wr(e.winrate),
    })),
    my_characters: s.my_characters.slice(0, 5).map((e) => ({
      char: charName(e.key), games: e.games, wr_pct: wr(e.winrate),
    })),
    stages: s.stages.slice(0, 6).map((e) => ({
      stage: stageName(e.key), games: e.games, wr_pct: wr(e.winrate),
    })),
    monthly: s.months.slice(-8).map((e) => ({
      month: e.key, games: e.games, wr_pct: wr(e.winrate),
    })),
    rivals: s.rivals.slice(0, 6).map((r) => ({
      name: r.name || null, code: r.code, games: r.games, w: r.wins, l: r.losses,
      wr_pct: wr(r.winrate),
    })),
    rage_quits: {
      they_quit_on_me: s.salt.opp_quits,
      i_quit: s.salt.my_quits,
      saltiest: s.salt.saltiest.slice(0, 2).map((r) => ({ code: r.code, quits: r.quits })),
    },
  }
}

function toolListGames(store, args, chips) {
  const filters = {
    myChar: resolveChar(args.my_char),
    oppChar: resolveChar(args.opp_char),
    stage: resolveStage(args.stage),
    result: args.result === 'win' || args.result === 'loss' ? args.result : '',
    teams: '',
    opponent: args.opp ? String(args.opp) : '',
    start: '',
    end: '',
  }
  const sort = args.newest_first === false ? 'oldest' : 'newest'
  const filtered = applyFilters(store.games, filters, sort)
  const limit = Math.min(Math.max(1, Number(args.limit) || 10), 20)
  return {
    matched: filtered.length,
    games: filtered.slice(0, limit).map((g) => gameRow(g, chips)),
  }
}

function toolListCombos(store, args, chips) {
  const charId = resolveChar(args.character)
  const minD = args.min_damage != null ? Number(args.min_damage) : null
  const rows = store.combos
    .filter((c) => (charId === '' || String(c.character) === charId)
      && (minD == null || (c.damage || 0) >= minD)
      && (!args.kills_only || c.did_kill))
    .sort((a, b) => (b.damage || 0) - (a.damage || 0))
  const limit = Math.min(Math.max(1, Number(args.limit) || 8), 15)
  return {
    matched: rows.length,
    combos: rows.slice(0, limit).map((c) => {
      const vg = c.vault_games || {}
      const dmg = Math.round(c.damage || 0)
      chips.push({
        hash: vg.content_hash,
        label: `${dmg}%${c.did_kill ? ' kill' : ''} combo · ${charName(c.character)} vs ${charName(c.opp_character)}`,
        icon: c.character,
        sf: c.start_frame,
        ef: c.end_frame,
        dmg: c.damage,
      })
      return {
        char: charName(c.character),
        vs: charName(c.opp_character),
        dmg_pct: dmg,
        kill: !!c.did_kill,
        true_combo: c.true_combo === true,
        moves: (c.moves || [])
          .map((m) => moveName(m.move_id) + (m.hits > 1 ? ` x${m.hits}` : ''))
          .join(' -> ') || null,
        pct_range: c.start_percent != null
          ? `${Math.round(c.start_percent)}->${Math.round(c.end_percent)}%` : null,
        stage: stageName(vg.stage),
        date: (vg.start_at || '').slice(0, 10),
      }
    }),
  }
}

function toolHeadToHead(store, args, chips) {
  const q = String(args.opponent || '').trim().toUpperCase()
  if (!q) return { error: 'opponent is required' }
  const matches = store.games.filter((g) => opps(g).some((p) => (p.code || '').toUpperCase().includes(q)
    || (p.name || '').toUpperCase().includes(q)))
  if (!matches.length) return { matched_games: 0, note: 'no games against that opponent' }
  let w = 0, l = 0
  const codes = new Set()
  const theirChars = new Map()
  const myChars = new Map()
  const rec = (map, key) => {
    let r = map.get(key)
    if (!r) { r = { games: 0, w: 0, l: 0 }; map.set(key, r) }
    return r
  }
  for (const g of matches) {
    const o = opps(g).find((p) => (p.code || '').toUpperCase().includes(q)
      || (p.name || '').toUpperCase().includes(q))
    if (g.result === 'win') w++
    else if (g.result === 'loss') l++
    if (o?.code) codes.add(o.code)
    if (o?.character != null) {
      const r = rec(theirChars, o.character)
      r.games++
      if (g.result === 'win') r.w++
      else if (g.result === 'loss') r.l++
    }
    const m = me(g)
    if (m?.character != null) rec(myChars, m.character).games++
  }
  const recent = matches
    .slice()
    .sort((a, b) => (b.start_at || '').localeCompare(a.start_at || ''))
  return {
    matched_games: matches.length,
    codes: [...codes].slice(0, 4),
    record: { w, l, wr_pct: w + l ? wr(w / (w + l)) : null },
    their_characters: [...theirChars.entries()]
      .sort((a, b) => b[1].games - a[1].games)
      .map(([c, r]) => ({ char: charName(c), games: r.games, w: r.w, l: r.l })),
    my_characters: [...myChars.entries()]
      .sort((a, b) => b[1].games - a[1].games)
      .map(([c, r]) => ({ char: charName(c), games: r.games })),
    last_games: recent.slice(0, 5).map((g) => gameRow(g, chips)),
  }
}

const TOOLS = {
  get_overview: toolGetOverview,
  list_games: toolListGames,
  list_combos: toolListCombos,
  head_to_head: toolHeadToHead,
}

function execTool(store, toolCall, chips) {
  const name = toolCall.function?.name
  const fn = TOOLS[name]
  if (!fn) return { error: `unknown tool ${name}` }
  let args = {}
  try {
    const raw = toolCall.function.arguments
    if (raw && raw.trim()) args = JSON.parse(raw)
  } catch (e) {
    return { error: `bad tool arguments: ${e.message}` }
  }
  try {
    return fn(store, args, chips)
  } catch (e) {
    return { error: `${name} failed: ${e.message}` }
  }
}

// ── chat state (module scope so tab switches don't lose an in-flight turn) ──

const chat = { api: [], display: [], busy: false, typing: null }
let loaded = false
let live = null   // the currently-mounted UI, or null

// Multi-thread history: every conversation is kept (Apple-style, a history
// sheet rather than a sidebar — phones don't have room for panes). The
// active thread's messages mirror into `chat` for the live UI.
//
// Threads also sync through the vault (vault-read chats-get/chats-put) so the
// same conversations are there on every paired device. Offline-first: this
// device always works from localStorage and reconciles when it can — nothing
// waits on the network, and the desktop does not have to be running. The merge
// is per-thread last-write-wins on `updated`, with tombstones for deletes so a
// device that has been offline can't resurrect a thread deleted elsewhere.
const THREADS_KEY = 'nucleus.randall.threads'
const MAX_THREADS = 30
const SYNC_EVERY = 30_000     // don't re-reconcile on every tab switch
const threads = { list: [], activeId: null, tombs: [] }
let syncing = false
let lastSync = 0
let pushTimer = 0

const threadTitle = (api) => {
  const first = api.find((m) => m.role === 'user')
  const t = (first?.content || 'New chat').replace(/\s+/g, ' ').trim()
  return t.length > 44 ? `${t.slice(0, 44)}…` : t
}

function activeThread() {
  return threads.list.find((t) => t.id === threads.activeId) || null
}

function loadChat() {
  if (loaded) return
  loaded = true
  try {
    const raw = localStorage.getItem(THREADS_KEY)
    if (raw) {
      const saved = JSON.parse(raw)
      threads.list = Array.isArray(saved.list) ? saved.list : []
      threads.activeId = saved.activeId ?? threads.list[0]?.id ?? null
      threads.tombs = Array.isArray(saved.tombs) ? saved.tombs : []
    } else {
      // migrate the single-thread era in place
      const legacy = localStorage.getItem(STORE_KEY)
      if (legacy) {
        const old = JSON.parse(legacy)
        if (Array.isArray(old.api) && old.api.length) {
          const t = { id: `t${Math.random().toString(36).slice(2, 9)}`,
                      title: threadTitle(old.api), updated: 0,
                      api: old.api, display: old.display || [] }
          threads.list = [t]
          threads.activeId = t.id
        }
        localStorage.removeItem(STORE_KEY)
      }
    }
  } catch { /* corrupt/private mode — start fresh */ }
  const t = activeThread()
  chat.api = t ? t.api : []
  chat.display = t ? t.display : []
}

function persistThreads() {
  threads.list.sort((a, b) => (b.updated || 0) - (a.updated || 0))
  if (threads.list.length > MAX_THREADS) threads.list.length = MAX_THREADS
  try {
    localStorage.setItem(THREADS_KEY, JSON.stringify(threads))
  } catch { /* quota — the session still works from memory */ }
}

function persistChat() {
  // Trim whole leading turns: history must never start mid-tool-exchange.
  while (chat.api.length > MAX_API_MSGS
    || (chat.api.length && chat.api[0].role !== 'user')) chat.api.shift()
  if (chat.display.length > 60) chat.display = chat.display.slice(-60)
  let t = activeThread()
  if (!t) {
    t = { id: `t${Math.random().toString(36).slice(2, 9)}` }
    threads.list.unshift(t)
    threads.activeId = t.id
  }
  t.api = chat.api
  t.display = chat.display
  t.title = threadTitle(chat.api)
  t.updated = Date.now()
  persistThreads()
  scheduleSync()
}

function newChat() {
  chat.api = []
  chat.display = []
  chat.typing = null
  threads.activeId = null   // first message creates + persists the thread
  persistThreads()
  if (live) live.redraw()
}

function switchThread(id) {
  const t = threads.list.find((x) => x.id === id)
  if (!t) return
  threads.activeId = id
  chat.api = t.api
  chat.display = t.display
  chat.typing = null
  persistThreads()
  if (live) live.redraw()
}

function deleteThread(id) {
  threads.list = threads.list.filter((x) => x.id !== id)
  // tombstone, so the next reconcile deletes it in the vault too instead of
  // pulling it back down from a device that still has it
  threads.tombs.push({ id, at: Date.now() })
  if (threads.tombs.length > MAX_THREADS) threads.tombs.splice(0, threads.tombs.length - MAX_THREADS)
  if (threads.activeId === id) {
    threads.activeId = null
    chat.api = []
    chat.display = []
  }
  persistThreads()
  if (live) live.redraw()
  scheduleSync(300)
}

// ── vault sync ─────────────────────────────────────────────────────────────

const wireThread = (t) => ({
  id: t.id, title: t.title || 'Chat', updated: t.updated || 0,
  api: t.api || [], display: t.display || [],
})

function scheduleSync(delay = 1500) {
  clearTimeout(pushTimer)
  pushTimer = setTimeout(() => {
    if (chat.busy) { scheduleSync(2000); return }   // mid-turn: try again after
    syncThreads(true)
  }, delay)
}

async function syncThreads(force = false) {
  if (syncing || chat.busy || !getToken()) return
  if (!force && Date.now() - lastSync < SYNC_EVERY) return
  syncing = true
  try {
    const remote = await chatsGet()
    const rows = remote.threads || []
    const byId = new Map(threads.list.map((t) => [t.id, t]))
    const remoteIds = new Set()
    let changed = false

    for (const r of rows) {
      remoteIds.add(r.id)
      // deleted here after the remote copy was written -> stays deleted
      if (threads.tombs.some((t) => t.id === r.id && t.at >= (r.updated || 0))) continue
      const local = byId.get(r.id)
      if (!local) {
        threads.list.push(wireThread(r))
        changed = true
      } else if ((r.updated || 0) > (local.updated || 0)) {
        Object.assign(local, wireThread(r))
        if (local.id === threads.activeId) {
          chat.api = local.api
          chat.display = local.display
        }
        changed = true
      }
    }

    // anything newer here than there (including threads it has never seen)
    const push = threads.list.filter((t) => {
      const r = rows.find((x) => x.id === t.id)
      return !r || (t.updated || 0) > (r.updated || 0)
    })
    const deleted = threads.tombs.map((t) => t.id).filter((id) => remoteIds.has(id))
    if (push.length || deleted.length) {
      await chatsPut(push.map(wireThread), deleted)
    }
    threads.tombs = []
    lastSync = Date.now()
    persistThreads()
    if (changed && live) live.redraw()
  } catch {
    // offline or vault unreachable: the local copy stays authoritative and
    // the next mount tries again. Never surfaced — chat keeps working.
  } finally {
    syncing = false
  }
}

// ── network ────────────────────────────────────────────────────────────────

function post(payload) {
  return fetch(FN_CHAT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: CFG.anonKey,
      Authorization: `Bearer ${CFG.anonKey}`,
    },
    body: JSON.stringify({ token: getToken(), ...payload }),
  })
}

async function callChat(messages, tools) {
  const r = await post({ messages, model: modelKey(), ...(tools ? { tools } : {}) })
  const out = await r.json().catch(() => ({}))
  if (!r.ok && !out.error) throw new Error(`HTTP ${r.status}`)
  return out
}

// ── model choice + the monthly budget meter ─────────────────────────────

function modelKey() {
  try { return localStorage.getItem(MODEL_KEY) || MODELS[0].key } catch { return MODELS[0].key }
}
function setModelKey(k) {
  try { localStorage.setItem(MODEL_KEY, k) } catch { /* private mode */ }
}
const modelLabel = (k) => MODELS.find((m) => m.key === k)?.label || MODELS[0].label

// Cached for the session: the meter is context, not a live readout, and every
// check is an OpenRouter round trip on the owner's key.
let usageCache = null
async function fetchUsage(force = false) {
  if (usageCache && !force) return usageCache
  try {
    const r = await post({ action: 'usage' })
    const out = await r.json()
    if (out.error) return null
    usageCache = out
    return out
  } catch { return null }
}

// ── one full turn: user text -> tool loop -> final answer ──────────────────

async function runTurn(store, text) {
  chat.busy = true
  chat.typing = 'thinking…'
  chat.api.push({ role: 'user', content: text })
  chat.display.push({ role: 'user', content: text, at: Date.now() })
  persistChat()
  if (live) live.redraw()

  const chips = []
  // What this turn did, kept on its reply for "Report this chat": the model
  // picked, how many model calls it took, which tools ran, and whatever the
  // edge function reported about the served model and usage.
  const turn = { model: modelKey(), rounds: 0, tools: [], served: [], usage: null }
  const settle = (entry) => chat.display.push({ ...entry, at: Date.now(), meta: turn })
  try {
    for (let round = 0; ; round++) {
      const useTools = round < MAX_ROUNDS
      if (!useTools) {
        // out of rounds — force a tool-free final answer instead of dead-ending
        chat.api.push({
          role: 'user',
          content: '(You have plenty of data — answer NOW from what you already gathered, no more tool calls.)',
        })
      }
      const messages = [{ role: 'system', content: systemPrompt() }, ...chat.api]
      const out = await callChat(messages, useTools ? TOOL_SCHEMAS : null)
      turn.rounds++
      if (out.model && !turn.served.includes(out.model)) turn.served.push(String(out.model).slice(0, 80))
      if (out.usage && typeof out.usage === 'object') turn.usage = addUsage(turn.usage, out.usage)

      if (out.error) {
        turn.error = String(out.error).slice(0, 200)
        if (out.error === 'no_ai') {
          settle({ role: 'upsell' })
        } else if (out.error === 'invalid_token' || out.error === 'inactive') {
          settle({
            role: 'error',
            content: 'This device token is no longer valid — pair again from desktop.',
          })
        } else if (out.error === 'budget') {
          settle({
            role: 'error',
            content: "You've used this month's Randall budget. It refills on the 1st.",
          })
        } else if (out.error === 'paused') {
          settle({ role: 'error', content: 'Randall is paused right now. Check back soon.' })
        } else if (out.error === 'rate_limited') {
          const wait = Number(out.retry_after)
          settle({
            role: 'error',
            content: wait > 0 && wait < 120
              ? `Slow down a sec. Try again in ${Math.ceil(wait)} seconds.`
              : "That's a lot of messages today. Try again later.",
          })
        } else {
          settle({ role: 'error', content: `Randall hit a snag: ${out.error}` })
        }
        return
      }

      const msg = out.message
      if (!msg) throw new Error('empty model response')
      chat.api.push({
        role: 'assistant',
        content: msg.content || '',
        ...(msg.tool_calls?.length ? { tool_calls: msg.tool_calls } : {}),
      })

      if (msg.tool_calls?.length && useTools) {
        for (const tc of msg.tool_calls) {
          chat.typing = TOOL_LABELS[tc.function?.name] || 'working…'
          turn.tools.push(tc.function?.name || 'unknown')
          if (live) live.redraw()
          const result = execTool(store, tc, chips)
          chat.api.push({
            role: 'tool',
            tool_call_id: tc.id,
            name: tc.function?.name,
            content: JSON.stringify(result),
          })
        }
        chat.typing = 'thinking…'
        if (live) live.redraw()
        continue
      }

      const content = (msg.content || '').trim()
      settle({
        role: 'randall',
        content: content || "(Randall had nothing to say — try rephrasing.)",
        chips: dedupeChips(chips).slice(0, 6),
      })
      return
    }
  } catch (e) {
    turn.error = String(e.message).slice(0, 200)
    settle({
      role: 'error',
      content: `Could not reach Randall: ${e.message}`,
    })
  } finally {
    chat.busy = false
    chat.typing = null
    persistChat()
    if (live) live.redraw()
  }
}

function addUsage(total, usage) {
  const out = { ...(total || {}) }
  for (const key of ['prompt_tokens', 'completion_tokens', 'cost']) {
    if (Number.isFinite(usage[key])) out[key] = Math.round(((out[key] || 0) + usage[key]) * 1e6) / 1e6
  }
  return out
}

// ── "Report this chat" ─────────────────────────────────────────────────────

function reportInfo() {
  return {
    appVersion: CFG.version || '0.0.0',
    model: modelKey(),
    usage: usageCache ? { weekly_allowance: usageCache.weekly_allowance, remaining: usageCache.remaining } : null,
    userAgent: (navigator.userAgent || '').slice(0, 160),
  }
}

function localStore() {
  try { return window.localStorage } catch { return null }   // private mode can throw on access
}

function currentReportThread() {
  const t = activeThread()
  return { id: t?.id || 'unsaved', title: t?.title || threadTitle(chat.api), updated: t?.updated || 0,
           api: chat.api, display: chat.display }
}

function openReportSheet() {
  const sh = sheet('Report this chat')
  const secrets = [getToken()].filter(Boolean)
  // One timestamp per sheet: the same note gives the same bytes, so a retry
  // after a failed upload goes back into the same remote report.
  const openedAt = Date.now()
  const build = (note = '', contact = '') => buildMobileReport({
    thread: currentReportThread(), note, contact, info: reportInfo(), secrets, now: openedAt,
  })
  let preview = build()
  const body = el(`<div class="rd-report">
    <p>${esc(CONSENT_LINE)}</p>
    <textarea class="rd-report-note" maxlength="4000"
      placeholder="What went wrong? (optional)"></textarea>
    <input class="rd-report-contact" type="text" maxlength="200" autocomplete="off"
      placeholder="How can we reach you? Discord or email (optional)">
    <details class="rd-report-what"></details>
    <p class="rd-report-error" hidden></p>
    <button class="rd-report-send">Send</button>
  </div>`)
  const what = body.querySelector('.rd-report-what')
  const drawWhat = () => {
    what.innerHTML = `<summary>What gets sent</summary>
      <ul>${describeReport(preview).map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
      <p>Not included:</p>
      <ul>${NOT_INCLUDED.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
      <details><summary>Show the transcript as it will be sent</summary><pre>${esc(preview.transcript)}</pre></details>`
  }
  drawWhat()
  const sendBtn = body.querySelector('.rd-report-send')
  const errorEl = body.querySelector('.rd-report-error')
  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text }
  sendBtn.addEventListener('click', async () => {
    if (sendBtn.disabled) return
    const note = body.querySelector('.rd-report-note').value
    const contact = body.querySelector('.rd-report-contact').value
    const built = build(note, contact)
    if (built.conversationText !== preview.conversationText) {
      // The thread moved on since the preview: show the new one, send nothing.
      preview = built
      drawWhat()
      showError('The conversation changed since the preview. Check what gets sent, then tap Send again.')
      return
    }
    sendBtn.disabled = true
    sendBtn.textContent = 'Sending…'
    showError('')
    try {
      const zip = zipStore(built.files)
      const sent = await sendMobileReport({
        zip, meta: built.meta, url: CFG.bugreportUrl || undefined, storage: localStore(),
      })
      sh.close()
      toast(`Report sent — thank you. Reference ${String(sent.id).slice(0, 8)}.`)
    } catch (e) {
      showError(errorText(e))
      sendBtn.disabled = false
      sendBtn.textContent = 'Send'
    }
  })
  sh.body.appendChild(body)
}

function systemPrompt() {
  return `${SYSTEM_PROMPT}\n\nToday is ${new Date().toISOString().slice(0, 10)}.`
}

function dedupeChips(chips) {
  const seen = new Set()
  return chips.filter((c) => {
    if (!c.hash) return false
    const k = `${c.hash}:${c.sf ?? ''}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

// ── rendering ──────────────────────────────────────────────────────────────

// Randall's face: Watch Lite's own cloud drawing (itemArt.randallSvg)
const RANDALL_FACE = `<span class="rd-face" aria-hidden="true">${randallSvg()}</span>`

// Text that got decoded as latin-1 somewhere upstream reads as "Â·" / "â€”".
// Repair by re-encoding those code points and decoding them as UTF-8 — gated
// on the telltale pattern so clean text is never touched, and on the whole
// string being latin-1 range so a half-mangled reply is left alone.
// A UTF-8 byte pair read as latin-1 leaves a 0xC2/0xC3 lead followed by a
// continuation byte -- the 'Â·' bullets. Scan for that pair in code points.
function looksMojibaked(text) {
  for (let i = 0; i + 1 < text.length; i++) {
    const a = text.charCodeAt(i)
    if (a !== 0xc2 && a !== 0xc3) continue
    const b = text.charCodeAt(i + 1)
    if (b >= 0x80 && b <= 0xbf) return true
  }
  return false
}
function demojibake(text) {
  if (!looksMojibaked(text)) return text
  const codes = [...text].map((c) => c.charCodeAt(0))
  if (codes.some((c) => c > 0xff)) return text
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(codes))
  } catch { return text }
}

/** Escape, then allow the light markdown the model actually emits: **bold**,
 * \`code\`, bullet lines, paragraph breaks. No raw HTML ever passes through. */
function mdLite(text) {
  const paras = esc(demojibake(text)).split(/\n{2,}/)
  return paras.map((p) => {
    const html = p
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^[-*] (.*)$/gm, '<span class="rd-li">$1</span>')
      .replace(/\n/g, '<br>')
    return `<p>${html}</p>`
  }).join('')
}

// Which of a turn's references get rendered as playable clips rather than
// chips: the ones that point at a MOMENT (a combo has start/end frames), not
// a whole game. Capped, because each card is a clip download — the rest stay
// as chips, which cost nothing until tapped.
const MAX_INLINE_CLIPS = 3
const clipIdx = (chips) => new Set((chips || [])
  .map((c, i) => (c.sf != null && c.hash ? i : -1))
  .filter((i) => i >= 0)
  .slice(0, MAX_INLINE_CLIPS))

function chipsHtml(chips, skip = new Set()) {
  if (!chips?.length) return ''
  const rows = chips.map((c, i) => ({ c, i })).filter(({ i }) => !skip.has(i))
  if (!rows.length) return ''
  return `<div class="rd-chips">${rows.map(({ c, i }) => `
    <button class="rd-chip" data-chip="${i}">
      ${c.icon != null ? `<img src="${stockSrc(c.icon, 0)}" alt="" onerror="this.style.visibility='hidden'">` : ''}
      <span>${esc(c.label)}</span>
      <span class="rd-chip-go">›</span>
    </button>`).join('')}</div>`
}

function messageHtml(m, i) {
  if (m.role === 'user') {
    return `<div class="rd-msg rd-msg--user">${mdLite(m.content)}</div>`
  }
  if (m.role === 'error') {
    return `<div class="rd-msg rd-msg--randall rd-msg--error">${mdLite(m.content)}</div>`
  }
  if (m.role === 'upsell') {
    return `<div class="rd-msg rd-msg--randall rd-upsell">
      ${RANDALL_FACE}
      <p><b>Randall runs on the AI tier.</b></p>
      <p>The AI coach reasons over your real numbers on our dime — it's part of
      the $10 Nucleon AI tier on Patreon. Browsing your vault stays free.</p>
      <a class="rd-upsell-cta" href="${PATREON_URL}" target="_blank" rel="noopener">Join on Patreon</a>
    </div>`
  }
  return `<div class="rd-turn" data-turn="${i}">
    <div class="rd-msg rd-msg--randall">${mdLite(m.content)}</div>
    <div class="rd-clips"></div>
    ${chipsHtml(m.chips, clipIdx(m.chips))}
  </div>`
}

function openChip(store, chip) {
  const g = store.games.find((x) => x.content_hash === chip.hash)
  if (!g) { toast('Game not in the library yet — pull to refresh.'); return }
  if (chip.sf != null) {
    openDetail(g, {
      focusStartFrame: chip.sf,
      focusEndFrame: chip.ef,
      focusDamage: chip.dmg,
    })
  } else {
    openDetail(g)
  }
}

export function renderRandall(root, store) {
  loadChat()
  syncThreads()      // background reconcile; never blocks the UI
  root.innerHTML = ''

  const NEW_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>`
  const HISTORY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>`
  const CFG_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 7h9M17 7h3M4 17h3M11 17h9"/>
    <circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/></svg>`
  const REPORT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/></svg>`
  const head = el(`<div class="head frosted">
    <div><h1>Randall</h1><div class="sub" id="rd-sub">${num(store.games.length)} games · ${esc(modelLabel(modelKey()))}</div></div>
    <span class="grow"></span>
    <button class="headbtn" id="rd-report" aria-label="Report this chat" hidden>${REPORT_ICON}</button>
    <button class="headbtn" id="rd-cfg" aria-label="Randall settings">${CFG_ICON}</button>
    <button class="headbtn" id="rd-history" aria-label="Chat history">${HISTORY_ICON}</button>
    <button class="headbtn" id="rd-new" aria-label="New chat">${NEW_ICON}</button>
  </div>`)
  root.appendChild(head)

  const body = el('<div class="pagebody"></div>')
  root.appendChild(body)
  const thread = el('<div class="rd-thread"></div>')
  body.appendChild(thread)

  const inputbar = el(`<div class="rd-inputbar frosted">
    <div class="rd-inputbar-inner">
      <input class="rd-input" type="text" placeholder="Ask Randall about your games"
             autocomplete="off" autocapitalize="sentences" enterkeyhint="send">
      <button class="rd-send" aria-label="Send" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>
      </button>
    </div>
  </div>`)
  // position:fixed is viewport-relative regardless of where the node lives,
  // so keep it inside root — renderTab's app wipe then removes it with the tab.
  root.appendChild(inputbar)
  const input = inputbar.querySelector('.rd-input')
  const sendBtn = inputbar.querySelector('.rd-send')

  const ui = {
    redraw() {
      if (!root.isConnected) {
        // tab switched away mid-turn: drop the binding, state is persisted
        if (live === ui) live = null
        return
      }
      drawThread()
      // Only a conversation that exists, and not mid-turn, can be reported.
      head.querySelector('#rd-report').hidden = !chat.display.length || chat.busy
      sendBtn.disabled = chat.busy || !input.value.trim()
      input.disabled = chat.busy
    },
  }
  live = ui

  function drawThread() {
    if (!store.games.length) {
      thread.innerHTML = `<p class="empty">No games synced yet — Randall needs
        your library first. Sync from the desktop app, then come back.</p>`
      return
    }
    if (!chat.display.length && !chat.busy) {
      thread.innerHTML = `<div class="rd-empty">
        ${RANDALL_FACE}
        <h2>Ask Randall</h2>
        <p>Your coach reads your real numbers — record, matchups, rivals,
        combos — and nothing it can't back up.</p>
        <div class="rd-starters">${STARTERS.map((s) => `
          <button class="rd-starter">${esc(s)}</button>`).join('')}</div>
      </div>`
      return
    }
    thread.innerHTML = chat.display.map((m, i) => messageHtml(m, i)).join('')
      + (chat.typing ? `<div class="rd-msg rd-msg--randall rd-typing">
          <i></i><i></i><i></i><span>${esc(chat.typing)}</span></div>` : '')
    // the clips are real canvases, so they get built after the HTML lands;
    // they lazy-load and only paint while on screen, which is what makes it
    // affordable to hang several off one answer
    for (const turn of thread.querySelectorAll('.rd-turn')) {
      const m = chat.display[Number(turn.dataset.turn)]
      const slot = turn.querySelector('.rd-clips')
      if (!m?.chips?.length || !slot) continue
      const cards = [...clipIdx(m.chips)].map((i) => {
        const c = m.chips[i]
        return clipCard({
          contentHash: c.hash,
          startFrame: c.sf,
          endFrame: c.ef,
          title: c.label,
          onExpand: () => openChip(store, c),
        })
      })
      if (cards.length) slot.appendChild(clipReel(cards))
    }
    // keep the newest message on screen
    requestAnimationFrame(() => {
      window.scrollTo({ top: document.body.scrollHeight })
    })
  }

  function send(text) {
    const t = (text || '').trim()
    if (!t || chat.busy) return
    input.value = ''
    runTurn(store, t)
    ui.redraw()
  }

  head.querySelector('#rd-new').addEventListener('click', () => {
    if (chat.busy) { toast('Randall is mid-thought — give him a second.'); return }
    newChat()
  })
  head.querySelector('#rd-report').addEventListener('click', () => {
    if (chat.busy) { toast('Randall is mid-thought — give him a second.'); return }
    openReportSheet()
  })
  head.querySelector('#rd-cfg').addEventListener('click', () => {
    const sh = sheet('Randall')
    const current = modelKey()
    for (const m of MODELS) {
      const row = sheetRow({
        label: m.label, sub: m.sub, checked: m.key === current,
      })
      row.addEventListener('click', () => {
        setModelKey(m.key)
        sh.close()
        head.querySelector('#rd-sub').textContent =
          `${num(store.games.length)} games · ${modelLabel(m.key)}`
        toast(`Randall is now running on ${m.label}.`)
      })
      sh.body.appendChild(row)
    }
    // Anthropic-style fill, no dollar figures — same call the desktop makes.
    const meter = el(`<div class="rd-usage">
      <div class="rd-usage-top"><span>Monthly usage</span><span class="rd-usage-pct">…</span></div>
      <div class="rd-usage-bar"><i style="width:0%"></i></div>
      <p class="footnote" style="margin-top:6px">Your Randall budget refills on the 1st of each month.</p>
    </div>`)
    sh.body.appendChild(meter)
    fetchUsage(true).then((u) => {
      if (!u || u.remaining == null || !u.weekly_allowance) {
        meter.querySelector('.rd-usage-pct').textContent = '—'
        return
      }
      const used = Math.max(0, Math.min(1, (u.weekly_allowance - u.remaining) / u.weekly_allowance))
      meter.querySelector('.rd-usage-pct').textContent = used >= 0.995
        ? 'limit reached' : `${Math.round(used * 100)}%`
      meter.querySelector('.rd-usage-bar i').style.width = `${Math.round(used * 100)}%`
      meter.classList.toggle('is-full', used >= 0.995)
    })
  })
  head.querySelector('#rd-history').addEventListener('click', () => {
    if (chat.busy) { toast('Randall is mid-thought — give him a second.'); return }
    const sh = sheet('Chats')
    if (!threads.list.length) {
      sh.body.appendChild(el('<p class="footnote" style="text-align:center;padding:10px">No past chats yet.</p>'))
    }
    for (const t of threads.list) {
      const when = t.updated
        ? new Date(t.updated).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        : ''
      const row = el(`<div class="sheet-row" role="button">
        <span class="sheet-row-text">
          <span class="sheet-row-label">${esc(t.title || 'Chat')}</span>
          <span class="sheet-row-sub">${esc(when)}${t.id === threads.activeId ? ' · current' : ''}</span>
        </span>
        <button class="linkish rd-del" aria-label="Delete chat">×</button>
      </div>`)
      row.addEventListener('click', (e) => {
        if (e.target.closest('.rd-del')) {
          deleteThread(t.id)
          sh.close()
          return
        }
        switchThread(t.id)
        sh.close()
      })
      sh.body.appendChild(row)
    }
  })
  input.addEventListener('input', () => { sendBtn.disabled = chat.busy || !input.value.trim() })
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(input.value) })
  sendBtn.addEventListener('click', () => send(input.value))

  thread.addEventListener('click', (e) => {
    const starter = e.target.closest('.rd-starter')
    if (starter) { send(starter.textContent); return }
    const chipBtn = e.target.closest('.rd-chip')
    if (!chipBtn) return
    const turn = e.target.closest('.rd-turn')
    if (!turn) return
    const m = chat.display[Number(turn.dataset.turn)]
    const chip = m?.chips?.[Number(chipBtn.dataset.chip)]
    if (chip) openChip(store, chip)
  })

  ui.redraw()
}
