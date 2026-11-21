// Human-readable per-frame readout helpers for the Watch Lite panel.

// Action-state label from ranges the analyzer trusts (no guessed ids).
export function stateLabel(s) {
  if (s <= 10) return 'dead/respawn'
  if (s >= 75 && s <= 91) return 'hitstun'
  if (s === 38) return 'tumble'
  if (s >= 212 && s <= 222) return 'grabbing'
  if (s >= 223 && s <= 232) return 'grabbed'
  if (s >= 239 && s <= 243) return 'thrown'
  if (s >= 199 && s <= 201) return 'teching'
  if (s >= 183 && s <= 201) return 'knocked down'
  if (s >= 252 && s <= 263) return 'on ledge'
  if (s === 181) return 'shieldstun'
  if (s >= 178 && s <= 182) return 'shielding'
  if (s === 236) return 'airdodge'
  if (s === 235) return 'spotdodge'
  if (s === 233 || s === 234) return 'rolling'
  if (s === 24) return 'jumpsquat'
  if (s >= 44 && s <= 64) return 'ground attack'
  if (s >= 65 && s <= 74) return 'aerial'
  if (s >= 341) return 'special'
  if (s >= 20 && s <= 23) return 'dash/run'
  if (s >= 15 && s <= 18) return 'walk'
  if (s === 14) return 'stand'
  if (s >= 25 && s <= 34) return 'airborne'
  return `state ${s}`
}


export function moveName(id, attackNames) {
  const nm = attackNames && attackNames[String(id)]
  return (nm && nm !== 'misc' && nm !== 'none') ? nm : null
}

// A compact GameCube controller as an SVG string: analog + c-stick with live
// positions, ABXY / Z / L / R / Start / d-pad lit when pressed. clamp helper
// keeps stick dots inside their gates.
const cl = (v) => Math.max(-1, Math.min(1, v || 0))
export function controllerSVG(mask, jx, jy, cx, cy) {
  const on = (bit, color) => ((mask & bit) ? color : '#2a3350')
  const A = 0x100, B = 0x200, X = 0x400, Y = 0x800, Z = 0x10, L = 0x40, R = 0x20, ST = 0x1000
  const U = 0x8, D = 0x4, RT = 0x2, LF = 0x1
  const sx = 38 + cl(jx) * 14, sy = 54 - cl(jy) * 14
  const kx = 118 + cl(cx) * 10, ky = 74 - cl(cy) * 10
  return `<svg viewBox="0 0 160 98" class="wl-ctrl" preserveAspectRatio="xMidYMid meet">
    <rect x="18" y="5" width="34" height="9" rx="4.5" fill="${on(L, '#8b93ff')}"/>
    <rect x="108" y="5" width="34" height="9" rx="4.5" fill="${on(R, '#8b93ff')}"/>
    <rect x="118" y="18" width="22" height="8" rx="4" fill="${on(Z, '#b06bff')}"/>
    <circle cx="80" cy="28" r="4" fill="${on(ST, '#cfd5e4')}"/>
    <circle cx="38" cy="54" r="17" fill="#0b0d13" stroke="#313a52" stroke-width="1.5"/>
    <circle cx="${sx}" cy="${sy}" r="6.5" fill="#dfe4f0"/>
    <g stroke="#0b0d13" stroke-width="1">
      <rect x="30" y="78" width="7" height="7" fill="${on(U, '#8b93ff')}"/>
      <rect x="30" y="88" width="7" height="7" fill="${on(D, '#8b93ff')}"/>
      <rect x="24" y="83" width="7" height="7" fill="${on(LF, '#8b93ff')}"/>
      <rect x="36" y="83" width="7" height="7" fill="${on(RT, '#8b93ff')}"/>
    </g>
    <circle cx="122" cy="46" r="12" fill="${on(A, '#4be0a0')}"/>
    <circle cx="103" cy="56" r="7" fill="${on(B, '#ff5470')}"/>
    <circle cx="120" cy="29" r="6" fill="${on(Y, '#c7ccd8')}"/>
    <circle cx="141" cy="40" r="6" fill="${on(X, '#c7ccd8')}"/>
    <circle cx="118" cy="76" r="12" fill="#0b0d13" stroke="#5a4d1c" stroke-width="1.5"/>
    <circle cx="${kx}" cy="${ky}" r="5.5" fill="#ffd24a"/>
  </svg>`
}
