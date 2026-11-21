import { useEffect, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName, formatDuration, formatDate, slippiProfileUrl, openSlippiProfile } from '../../shared/data/meleeNames'
import LiteButton from '../lib/LiteGate'
import ShareLinkButton from '../share/ShareLinkButton'
import { Randall } from '../../shared/ui/Sprites'
import { ENTITLEMENT_EVENT } from '../../shared/account/entitlement'

const API = `${BACKEND_URL}/api/nucleome`

// Exact-costume vanilla stock icon (backend falls back to the default color)
function StockIcon({ player }) {
  if (player?.character == null) return null
  return (
    <img
      className="replay-stock"
      src={`${API}/stock/${player.character}/${player.costume ?? 0}`}
      alt=""
      loading="lazy"
      onError={(e) => { e.target.style.display = 'none' }}
    />
  )
}

// slippi.gg's official rank icons, bundled (viewer/src/assets/ranks/)
const RANK_ICONS = import.meta.glob('../assets/ranks/*.svg',
  { eager: true, query: '?url', import: 'default' })

function rankIconUrl(tier) {
  if (!tier || tier === 'Pending') return null
  const roman = { 1: 'I', 2: 'II', 3: 'III' }
  let name
  if (tier === 'Grandmaster') {
    name = 'rank_Grand_Master'
  } else {
    const [word, num] = tier.split(' ')
    name = `rank_${word === 'Plat' ? 'Platinum' : word}_${roman[num]}`
  }
  const key = Object.keys(RANK_ICONS).find((k) => k.endsWith(`/${name}.svg`))
  return key ? RANK_ICONS[key] : null
}

// One side of a 1v1 row: rank badge, stacked name/tag, and character. `side`
// mirrors the layout so both players face the centered "vs":
//   left:  [rank] [name/tag] [char]      right: [char] [name/tag] [rank]
// Rank is each player's CURRENT Slippi rank (the .slp has no per-match rank);
// no real tier icon (unranked / no rating) → empty placeholder, same both sides.
// `stocks` = stocks left at the last frame, drawn as mini icons under the name.
function PlayerSide({ player, rank, side, stocks }) {
  const name = player?.name || (player?.type === 1 ? 'CPU' : 'Player')
  const tag = player?.code || ''
  const icon = rank?.ranked && rankIconUrl(rank.tier)
  const rankEl = icon ? (
    <img key="r" className="replay-player-rank" src={icon} alt=""
         title={`${rank.tier} — ${rank.rating}`} />
  ) : <span key="r" className="replay-player-rank replay-player-rank--empty" />
  const stockSrc = `${API}/stock/${player.character}/${player.costume ?? 0}`
  const hasProfile = slippiProfileUrl(player?.code)
  const idEl = (
    <div key="i" className="replay-player-id">
      {hasProfile ? (
        <button
          type="button"
          className="replay-player-name replay-player-name--link"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); openSlippiProfile(player.code) }}
          title={`Open ${player.code} on slippi.gg`}
        >
          {name}
        </button>
      ) : (
        <span className="replay-player-name">{name}</span>
      )}
      {tag && <span className="replay-player-tag">{tag}</span>}
      {stocks > 0 && (
        <span className="replay-player-stocks" title={`${stocks} stock${stocks > 1 ? 's' : ''} left`}>
          {Array.from({ length: stocks }).map((_, k) => (
            <img key={k} className="replay-player-stock-dot" src={stockSrc} alt="" />
          ))}
        </span>
      )}
    </div>
  )
  const charEl = (
    <div key="c" className="replay-player-char" title={charName(player.character)}>
      <StockIcon player={player} />
    </div>
  )
  return (
    <div className={`replay-player replay-player--${side}`}>
      {side === 'left' ? [rankEl, idEl, charEl] : [charEl, idEl, rankEl]}
    </div>
  )
}

// One replay row: result badge, the versus block, stage, time, Watch.
// `instant` skips the staggered entrance (page swaps within a month).
export default function ReplayRow({ g, i, ranks, stocks, onWatch, onLite, instant, selected, onSelect }) {
  const me = g.players.find((p) => p.port === g.user_port)
  const opps = g.players.filter((p) => p.port !== g.user_port)
  const gs = stocks[g.id] || {}
  const [cloud, setCloud] = useState({ synced: g.synced, url: g.share_url })
  useEffect(() => { setCloud({ synced: g.synced, url: g.share_url }) }, [g.synced, g.share_url])
  useEffect(() => {
    const clear = () => setCloud({ synced: false, url: null })
    window.addEventListener(ENTITLEMENT_EVENT, clear)
    return () => window.removeEventListener(ENTITLEMENT_EVENT, clear)
  }, [])
  return (
    <div className={`replay-row ${instant ? 'replay-row--instant' : ''} ${selected ? 'is-selected' : ''}`}
         style={{ '--row-i': Math.min(i, 14) }}>
      <label className="replay-select" title="Select to watch or record several games as one playlist. Shift-click selects everything between this and the last one you clicked.">
        <input type="checkbox" checked={selected}
               onChange={(e) => onSelect(g, e.nativeEvent.shiftKey)}
               aria-label="Select this game for a playlist (shift-click to select a range)" />
      </label>
      <div className="replay-cloud-result">
      <span className={`replay-result replay-result--${g.result || 'unknown'}`}>
        {g.result === 'win' ? 'W' : g.result === 'loss' ? 'L' : '–'}
      </span>
      <span className="replay-cloud-badges">
        {cloud.synced && <span title="In your cloud library" role="img" aria-label="In your cloud library"><Randall size={24} animated={false} /></span>}
        {cloud.url && <a href={cloud.url} target="_blank" rel="noopener noreferrer" title="Open shared replay" aria-label="Open shared replay">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 3v13M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" /></svg>
        </a>}
      </span>
      </div>
      {me && opps.length === 1 ? (
        <div className="replay-versus">
          <PlayerSide player={me} rank={ranks[me.code]} side="left" stocks={gs[me.port]} />
          <span className="replay-vs-mid">vs</span>
          <PlayerSide player={opps[0]} rank={ranks[opps[0].code]} side="right" stocks={gs[opps[0].port]} />
        </div>
      ) : (
        <div className="replay-versus replay-versus--multi">
          <span className="replay-chars">
            {g.players.map((p, idx) => (
              <span key={p.port}>
                {idx > 0 && <span className="replay-vs"> vs </span>}
                <StockIcon player={p} />
                {charName(p.character)}
              </span>
            ))}
          </span>
          <span className="replay-opponent">
            {opps.map((p) => p.name || p.code || (p.type === 1 ? 'CPU' : 'Player')).join(', ')}
          </span>
        </div>
      )}
      <span className="replay-stage">
        <img className="replay-stage-icon" src={`${API}/stage-icon/${g.stage}`} alt={stageName(g.stage)} loading="lazy"
             onError={(e) => { e.target.style.display = 'none' }} />
      </span>
      <span className="replay-when">{formatDate(g.start_at)}</span>
      <span className="replay-duration">{formatDuration(g.duration_s)}</span>
      <div className="replay-actions">
        {/* Always offered: sharing uploads the game if it isn't up yet, which
            is the only way a replay reaches the vault on the free tier. */}
        <ShareLinkButton gameId={g.id} players={g.players} onShared={(url) => setCloud({ synced: true, url })} />
        {/* any game with two or more players: 1v1s, doubles, FFAs, and games
            you watched rather than played */}
        {g.players.length >= 2 && (
          <LiteButton className="wl-trigger" onOpen={() => onLite(g)}
                      title="Preview in-app instantly (no Dolphin)">
            Lite
          </LiteButton>
        )}
        <button className="replay-watchmods" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); onWatch(g) }}
                title="Watch in-app — with skins, recording, and more">
          ▶ Watch
        </button>
      </div>
    </div>
  )
}
