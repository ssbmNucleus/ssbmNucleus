import { useId } from 'react'

const hex = value => {
  const color = String(value || 'FFFFFF').replace('#', '')
  return /^([\da-f]{6}|[\da-f]{8})$/i.test(color) ? `#${color}` : '#FFFFFF'
}

// The editor supplies display colors, after its native RGBY/RGB conversion.
// A human part can own several native records; its picker and illustration
// use the same representative channel, without exposing those records.
export function partColors(part, colors) {
  const keys = part.controls?.flatMap(control => typeof control === 'string'
    ? [control] : control.keys?.slice(0, 1) || [control.key])
    || (colors[part.id] !== undefined ? [part.id] : Object.keys(colors))
  return (keys.length ? keys : ['color1']).map(key => ({ key, color: hex(colors[key]) }))
}

function Fighter({ x, y, scale = 1, fill = '#56697a', fox = false }) {
  return <g transform={`translate(${x} ${y}) scale(${scale})`} fill={fill} className="effect-picto-context">
    {fox && <path d="M-16 16 Q-71 3 -63 50 Q-32 57 -14 35Z M-12 -32 L-22 -62 L1 -45 L22 -57 L15 -28Z" />}
    <circle cy="-30" r="17" /><path d="M-16 -9 Q0 -17 18 -8 L24 29 L10 38 L21 66 L4 71 L-8 38 L-19 67 L-36 60 L-23 25Z" />
    <path d="M-14 -4 L-34 22 L-27 35 L-11 20 M15 -2 L38 17 L31 30 L13 19" stroke={fill} strokeWidth="9" strokeLinejoin="round" />
  </g>
}

function Star({ x = 0, y = 0, size = 1, fill }) {
  return <path transform={`translate(${x} ${y}) scale(${size})`} d="M0 -20 L5 -5 L20 0 L5 5 L0 20 L-5 5 L-20 0 L-5 -5Z" fill={fill} />
}

function Glyph({ kind, fill, secondary, index = 0 }) {
  switch (kind) {
    case 'flame': return <path d="M-55 53 Q-86 8 -35 -28 Q-45 2 -26 10 Q-18 -41 8 -66 Q3 -26 30 -9 Q43 -30 38 -43 Q87 5 61 45 Q29 83 -12 60 Q-35 79 -55 53Z" fill={fill} />
    case 'wisp': return <g fill="none" stroke={fill} strokeWidth="10" strokeLinecap="round"><path d="M-44 63 Q-73 24 -32 -7 Q-13 -29 -27 -59" /><path d="M-1 64 Q-22 28 18 -4 Q44 -29 22 -71" /><path d="M43 54 Q20 29 57 1 Q76 -17 65 -42" /></g>
    case 'smoke': return <path d="M-63 37 C-102 21 -86 -22 -59 -20 C-79 -57 -27 -73 -8 -44 C15 -85 67 -55 54 -20 C96 -28 105 23 68 34 C88 69 24 80 5 57 C-30 81 -67 72 -63 37Z" fill={fill} />
    case 'dots': return <g fill={fill}>{[[-55,-30,10],[-17,38,7],[18,-55,8],[47,21,10],[64,-32,6],[-57,42,5],[10,-7,12]].map(([x,y,s],i) => <rect key={i} x={x} y={y} width={s} height={s} rx="1.5" transform={`rotate(${i * 8} ${x} ${y})`} />)}</g>
    case 'sparkles': return <g>{[[-50,-26,1],[4,-55,.7],[50,12,1.1],[-20,44,.6],[55,-45,.45]].map(([x,y,s],i) => <Star key={i} x={x} y={y} size={s} fill={fill} />)}</g>
    case 'bolt': return <path d="M-10 -85 L-48 -9 L-13 -16 L-37 78 L31 0 L-1 8 L40 -69Z" fill={fill} stroke={secondary} strokeWidth="4" strokeLinejoin="round" />
    case 'arcs': return <g stroke={fill} fill="none" strokeWidth="6" strokeLinejoin="round"><path d="M-68 -35 L-42 -51 L-19 -31 L7 -49 L23 -22 L57 -29 L76 -8" /><path d="M-73 12 L-48 -2 L-26 26 L7 15 L28 40 L62 24 L77 48" /><path d="M-49 62 L-16 48 L10 65 L43 51" /></g>
    case 'rings': return <g fill="none" stroke={fill} strokeWidth="7"><ellipse cy="-35" rx="59" ry="18" /><ellipse cy="8" rx="73" ry="21" /><ellipse cy="49" rx="61" ry="17" /></g>
    case 'swirl': return <g fill={fill}><path d="M-78 12 Q-97 -57 -20 -78 Q-51 -53 -40 -26 Q-75 -22 -78 12Z M-7 -80 Q75 -84 84 -12 Q59 -45 33 -36 Q27 -65 -7 -80Z M83 7 Q89 84 9 85 Q45 62 37 36 Q65 30 83 7Z M-10 82 Q-86 88 -85 9 Q-64 47 -38 36 Q-32 65 -10 82Z" /></g>
    case 'ribbon': return <path d="M-80 65 Q-78 -75 80 -63 Q8 -34 -5 60Z" fill={fill} />
    case 'cape': return <path d="M-46 -60 Q-8 -40 43 -55 Q19 -11 69 50 Q10 77 -71 48 Q-20 12 -46 -60Z" fill={fill} stroke={secondary} strokeWidth="3" />
    case 'notes': return <g fill={fill} stroke={fill} strokeWidth="8"><path d="M-19 35 L-19 -53 L35 -66 L35 21" fill="none" /><path d="M-19 -51 L35 -65 L35 -43 L-19 -30Z" stroke="none" /><ellipse cx="-32" cy="39" rx="17" ry="12" transform="rotate(-20 -32 39)" /><ellipse cx="22" cy="25" rx="17" ry="12" transform="rotate(-20 22 25)" /></g>
    case 'coin': return <g fill={fill} stroke={secondary} strokeWidth="4"><ellipse rx="38" ry="62" /><path d="M-8 -35 L8 -43 L8 40 M-10 40 L24 40" fill="none" /></g>
    case 'ice': return <path d="M0 -79 L55 16 L36 57 L-54 57 L-69 19Z M0 -79 L-12 34 L36 57 M-69 19 L-12 34 L55 16" fill={fill} stroke={secondary} strokeWidth="3" />
    case 'needles': return <g stroke={fill} strokeWidth="4">{Array.from({length: 9}, (_,i) => <path key={i} d="M39 0 L82 0" transform={`rotate(${i * 40 + index * 10})`} />)}<circle r="25" fill={secondary} stroke="none" /></g>
    default: return <g><circle r="63" fill={fill} /><path d="M-45 13 Q-51 -33 -10 -44" fill="none" stroke={secondary} strokeWidth="8" strokeLinecap="round" opacity=".8" /></g>
  }
}

function kindFor(effectId, part) {
  const name = `${part.id} ${part.label}`.toLowerCase()
  if (/wisp/.test(name)) return 'wisp'
  if (/smoke|dust/.test(name)) return 'smoke'
  if (/dots|square|particles/.test(name)) return 'dots'
  if (/sparkle|flash|flare|spark|burst/.test(name)) return 'sparkles'
  if (/arc|bolt|elec/.test(name)) return 'arcs'
  if (/swirl|torn/.test(name)) return 'swirl'
  if (/ring|ripple|magnet/.test(name)) return 'rings'
  if (/needle|line/.test(name)) return 'needles'
  if (/trail/.test(name)) return /spin|sword/.test(effectId) ? 'ribbon' : 'flame'
  if (/flame|fire|front|punch|fist/.test(name)) return 'flame'
  if (/sing/.test(effectId)) return 'notes'
  if (/cape/.test(effectId)) return 'cape'
  if (/coin/.test(effectId)) return 'coin'
  if (/spin|tornado|cyclone|upsmash|farore|transform/.test(effectId)) return 'swirl'
  if (/thunder$|electric|jolt|thunder_jolt/.test(effectId)) return 'bolt'
  if (/magnet/.test(effectId)) return 'rings'
  if (/fire|punch|kick|breath|foot|dragon|boost/.test(effectId)) return 'flame'
  if (/ice/.test(effectId)) return 'ice'
  if (/stone/.test(effectId)) return 'smoke'
  return 'orb'
}

// Positions describe a single effect scene, not a grid of part icons. A
// projectile's smoke follows its head; ground ripples sit beneath the fighter;
// arcs, rings and flare layers surround the same center.
function scenePart(effectId, part, index, count) {
  const label = `${part.id} ${part.label}`.toLowerCase()
  const projectile = /fireball|shadow_ball|charge_shot|charge_ball|missile|jolt|ice_shot|copy_ice/.test(effectId)
  const center = projectile ? 355 : 280
  let kind = kindFor(effectId, part)
  let x = center, y = 184, scale = 1.1, rotate = 0, opacity = 1
  if (/ground|landing|ripple|dust/.test(label)) { x = center - 35; y = 289; scale = .72; opacity = .75 }
  else if (/hand|backblast/.test(label)) { x = 153; y = 206; scale = .58; kind = 'smoke'; opacity = .7 }
  else if (/smoke|trail|wisp/.test(label)) { x = center - 106; y = 211; scale = .8; opacity = .85 }
  else if (/dots|square|particles|sparkle/.test(label)) { x = center - 20; y = 184; scale = 1.65 }
  else if (/flash|flare|burst|fist/.test(label)) { x = center + 69; y = 160; scale = .7 }
  else if (/ring|aura|charge|swirl|torn|bolt|arc/.test(label)) { x = center; scale = 1.5; opacity = .8 }
  if (/sing/.test(effectId)) { x = 280 + [-120, 5, 125][index % 3]; y = [152, 96, 174][index % 3]; scale = .62; kind = 'notes' }
  if (/cape/.test(effectId) && kind === 'cape') { x = 329; y = 196; scale = 1.2; rotate = -14 }
  if (/breath/.test(effectId) && kind === 'flame') { x = 342; rotate = 90; scale = count === 1 ? 1.4 : scale }
  if (projectile && kind === 'flame') rotate = -90
  if (/kick|foot/.test(effectId) && /front|main/.test(label)) { x = 360; y = 230; rotate = 75; scale = .9 }
  if (/note|coin/.test(kind)) y -= 15
  // Multiple color-bearing layers can occupy the same region. Let the
  // underlying colors contribute, instead of covering them with an opaque
  // duplicate silhouette (e.g. fire particles plus the flame texture).
  if (count > 1 && ['flame', 'orb', 'swirl', 'smoke'].includes(kind)) opacity = Math.min(opacity, .78)
  if (/inner/.test(label)) scale *= .72
  if (/outer/.test(label)) scale *= 1.2
  return { x, y, scale, rotate, opacity, kind }
}

export default function LiveEffectPictogram({ effectId, character, parts, selectedId, onSelect, colors = {} }) {
  const uid = useId().replace(/:/g, '')
  const c = key => hex(colors[key])
  const gradient = (part, suffix = '') => `${uid}-${parts.indexOf(part)}${suffix}`
  const paint = part => `url(#${gradient(part)})`
  const choose = (id, children, extra = {}) => {
    const part = parts.find(item => item.id === id)
    if (!part) return null
    return <g key={id} role="button" tabIndex="0" aria-label={`Edit ${part.label}`} aria-pressed={selectedId === id}
      data-part={id} className="effect-picto-part" onClick={() => onSelect(id)}
      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(id) } }} {...extra}>
      <title>{part.label}</title>{children}
    </g>
  }
  let drawing
  if (effectId === 'upb') {
    // Startup and charge flames share the pre-launch scene; everything else is flight.
    const startupScene = selectedId === 'startup' || selectedId === 'charge_flames'
    drawing = <>
      <text className="effect-picto-phase" x="280" y="32" textAnchor="middle">{startupScene ? 'STARTUP' : 'FLIGHT'}</text>
      <g transform="translate(155 0)" display={startupScene ? undefined : 'none'}>
      <Fighter x={125} y={214} scale={.77} fox />
      {choose('charge_flames', <>
        <g>{[[52,150,.42],[198,140,.46],[125,78,.38]].map(([x,y,sc],i) => <g key={i} transform={`translate(${x} ${y}) scale(${sc})`} opacity=".92">
          <Glyph kind="flame" fill={c('p_charge_flames_flame_c1')} secondary={c('p_charge_flames_flame_c2')} /></g>)}</g>
        <g>{[[22,190,.4],[228,196,.44]].map(([x,y,sc],i) => <g key={i} transform={`translate(${x} ${y}) scale(${sc})`} opacity=".9">
          <Glyph kind="wisp" fill={c('p_charge_flames_wisp_c1')} secondary={c('p_charge_flames_wisp_c2')} /></g>)}</g>
      </>)}
      {choose('startup', <>
        <g stroke={c('charge_lines')} strokeWidth="3" strokeLinecap="round" opacity=".9">{[69,85,103,143,163,182].map((x,i) => <path key={x} d={`M${x} ${105 + (i % 3)*17} L${x} 275`} />)}</g>
        <g stroke={c('rings')} fill="none" strokeWidth="6">{[173,223,276].map((y,i) => <ellipse key={y} cx="125" cy={y} rx={49+i*9} ry={13+i*2} />)}</g>
      </>)}
      </g>
      <g transform="translate(-102 0)" display={startupScene ? 'none' : undefined}>
      {choose('main_flame', <>
        <path d="M313 269 Q286 154 354 74 Q338 120 361 134 Q394 95 382 55 Q470 140 449 265 Q421 228 418 181 Q394 235 381 285 Q368 228 347 197 Q326 222 313 269Z" fill={c('fire')} opacity=".85" />
        <path d="M344 230 Q325 170 375 93 Q397 137 420 164 Q432 192 413 239 Q412 196 391 179 Q366 206 371 253Z" fill={c('tip')} />
        <ellipse cx="382" cy="172" rx="25" ry="51" fill={c('body')} opacity=".65" />
      </>)}
      <Fighter x={382} y={174} scale={.59} fox />
      {choose('flight_puffs', <>
        <g fill={c('trail')}><path d="M351 286 Q331 258 355 237 Q354 257 370 259 Q388 252 383 235 Q416 264 398 285 Q375 303 351 286Z" /><path d="M365 326 Q343 310 366 292 Q364 307 379 300 Q406 318 390 332Z" /></g>
        <g fill={c('small_trail')}><circle cx="325" cy="302" r="10" /><circle cx="416" cy="311" r="8" /><circle cx="337" cy="325" r="5" /></g>
      </>)}
      {choose('travel_sparkles', <>
        <g fill={c('dots')}>{[[305,244],[435,272],[322,281],[413,331],[456,226]].map(([x,y]) => <rect key={x} x={x} y={y} width="7" height="7" rx="1" />)}</g>
        <Star x={459} y={139} size={.85} fill={c('flare')} /><Star x={303} y={204} size={.55} fill={c('flare')} />
      </>)}
      </g>
    </>
  } else if (effectId === 'laser') {
    drawing = <>
      {choose('wide', <path d="M48 180 L145 98 L430 98 L513 180 L430 262 L145 262Z" fill={c('wide')} opacity=".3" />)}
      {choose('thin', <path d="M65 180 L155 141 L445 141 L500 180 L445 219 L155 219Z" fill={c('thin')} opacity=".68" />)}
      {choose('outline', <path d="M82 180 L164 164 L451 164 L490 180 L451 196 L164 196Z" fill={c('outline')} />)}
      {choose('center', <path d="M139 180 H444" stroke={c('center')} strokeWidth="8" strokeLinecap="round" />)}
      {choose('tip', <path d="M443 167 L482 180 L443 193Z" fill={c('tip')} />)}
    </>
  } else if (effectId === 'shine') {
    const ring = 'M274 67 L371 123 L371 235 L274 291 L177 235 L177 123Z M274 116 L220 147 L220 211 L274 243 L328 211 L328 147Z'
    drawing = <>
      <Fighter x={274} y={183} scale={.67} fox />
      {choose('shield', <path d={ring} fill={c('secondary')} fillRule="evenodd" stroke={c('primary')} strokeWidth="6" strokeLinejoin="round" />)}
      {choose('flash', <g><Star x={161} y={96} size={2.1} fill={c('flash1')} /><Star x={161} y={96} size={1.1} fill={c('flash2')} /></g>)}
      {choose('sparkles', <g>{[[413,91,.9],[439,211,.65],[119,245,.65],[334,322,.5],[402,294,.45]].map(([x,y,s]) => <Star key={x} x={x} y={y} size={s} fill={c('sparkles')} />)}</g>)}
    </>
  } else if (effectId === 'sword') {
    drawing = <>
      {choose('outer', <path d="M124 292 Q73 52 421 62 Q470 135 443 271 L405 270 Q425 146 395 109 Q149 87 162 287Z" fill={c('outer')} opacity=".82" />)}
      {choose('inner', <path d="M162 287 Q149 87 395 109 Q425 146 405 270 L353 270 Q377 178 350 155 Q197 132 192 283Z" fill={c('inner')} />)}
      <g className="effect-picto-context" stroke="#8294a5" strokeLinecap="round"><path d="M168 289 L437 272" strokeWidth="7" /><path d="M194 270 L197 304 M165 289 L138 292" strokeWidth="9" /></g>
    </>
  } else if (effectId === 'sideb') {
    drawing = <>
      {choose(parts[0]?.id, <>{[105,209,311].map((x,i) => <g key={x} opacity={.3+i*.3}><Fighter x={x} y={190} scale={.95} fill={paint(parts[0])} fox /></g>)}</>)}
      <Fighter x={421} y={190} scale={.95} fox />
    </>
  } else if (effectId === 'laser_ring') {
    drawing = choose(parts[0]?.id, <>
      <g stroke={c('color2')} strokeWidth="16" strokeLinecap="round" opacity=".5">{[[-60,-72],[0,-95],[56,-65],[70,14],[36,78],[-29,92],[-77,46]].map(([x,y],i) => <path key={i} d={`M${278+x*.45} ${180+y*.45} L${278+x} ${180+y}`} />)}</g>
      <g stroke={c('color1')} strokeWidth="5" strokeLinecap="round">{[[-60,-72],[0,-95],[56,-65],[70,14],[36,78],[-29,92],[-77,46]].map(([x,y],i) => <path key={i} d={`M${278+x*.3} ${180+y*.3} L${278+x} ${180+y}`} />)}</g>
      <Star x={278} y={180} size={1.6} fill={c('color1')} />
      <path className="effect-picto-context" d="M140 187 L232 187 L243 167 L237 154 L156 154 L131 177 L108 204 L128 222Z" fill="#6c8091" />
    </>)
  } else if (effectId === 'screw_attack') {
    drawing = <>
      <Fighter x={253} y={186} scale={.84} />
      {parts.map(part => choose(part.id, <g transform={part.id === 'Arc' ? 'translate(395 168) scale(.85)' : 'translate(253 185) scale(1.42)'}>
        <Glyph kind={part.id === 'Arc' ? 'arcs' : 'swirl'} fill={paint(part)} secondary={partColors(part, colors)[0].color} />
      </g>))}
    </>
  } else if (effectId === 'charge_flames') {
    drawing = <>
      <Fighter x={276} y={238} scale={.77} fox />
      {parts.map(part => choose(part.id, <g>{(part.id === 'Wisp' ? [[210,147,.67],[330,140,.85]] : [[240,245,.55],[303,209,.48],[237,104,.43]]).map(([x,y,s],i) => <g key={i} transform={`translate(${x} ${y}) scale(${s})`}>
        <Glyph kind={part.id === 'Wisp' ? 'wisp' : 'flame'} fill={paint(part)} secondary={partColors(part, colors)[0].color} />
      </g>)}</g>))}
    </>
  } else {
    const projectile = /fireball|shadow_ball|charge_shot|charge_ball|missile|jolt|ice_shot|copy_ice/.test(effectId)
    const ordered = parts.map((part, index) => ({ part, index, ...scenePart(effectId, part, index, parts.length) }))
      .sort((a, b) => (['dots', 'sparkles', 'arcs'].includes(a.kind) ? 1 : 0) - (['dots', 'sparkles', 'arcs'].includes(b.kind) ? 1 : 0))
    drawing = <>
      <path d="M84 298 H475" stroke="#344352" strokeWidth="2" className="effect-picto-context" />
      <Fighter x={projectile || /breath/.test(effectId) ? 137 : 280} y={223} scale={.8} />
      {ordered.map(({part, index, x, y, scale, rotate, opacity, kind}) => {
        const palette = partColors(part, colors)
        return choose(part.id, <g transform={`translate(${x} ${y}) rotate(${rotate}) scale(${scale})`} opacity={opacity}>
          <Glyph kind={kind} fill={paint(part)} secondary={palette.at(-1).color} index={index} />
        </g>)
      })}
    </>
  }
  return <svg className="effect-live-pictogram" viewBox="0 0 560 360" aria-label={`${character} effect colors`}>
    <defs>{parts.map(part => {
      const palette = partColors(part, colors)
      return <radialGradient key={part.id} id={gradient(part)} cx="40%" cy="35%" r="70%">
        {palette.map(({key, color}, i) => <stop key={`${key}-${i}`} offset={`${palette.length === 1 ? 0 : i * 100 / (palette.length - 1)}%`} stopColor={color} data-color-key={key} />)}
      </radialGradient>
    })}</defs>
    {drawing}
  </svg>
}
