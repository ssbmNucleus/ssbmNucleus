import { createContext, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

// ── custom tooltip layer (replaces native title= hovers) ──
// One fixed, styled box that follows the cursor. State lives in TooltipHost,
// and since {children} is a stable prop, mousemove re-renders ONLY the box —
// never the charts underneath.
export const TipCtx = createContext({ move: () => {}, hide: () => {} })

function TooltipBox({ tip }) {
  const above = tip.y > window.innerHeight * 0.55
  // Portal to <body>: tip.x/tip.y are viewport coords (clientX/clientY) and the
  // box is position:fixed, so it MUST resolve against the viewport. Rendered in
  // place it resolves against the nearest transformed/animated ancestor instead
  // (e.g. .app-content's mode-enter animation), landing far from the cursor.
  return createPortal(
    <div className="stats-tip" style={{
      left: Math.max(8, Math.min(tip.x + 14, window.innerWidth - 300)),
      top: above ? tip.y - 12 : tip.y + 16,
      transform: above ? 'translateY(-100%)' : undefined,
    }}>
      {tip.content}
    </div>,
    document.body,
  )
}

export function TooltipHost({ children }) {
  const [tip, setTip] = useState(null)
  const api = useMemo(() => ({
    move: (e, content) => setTip({ x: e.clientX, y: e.clientY, content }),
    hide: () => setTip(null),
  }), [])
  return (
    <TipCtx.Provider value={api}>
      {children}
      {tip && <TooltipBox tip={tip} />}
    </TipCtx.Provider>
  )
}

// standard tooltip body: bold title + aligned label/value rows
export function TipCard({ title, rows, icon }) {
  return (
    <>
      <div className="stats-tip-title">
        {icon && <img className="stats-tip-title-icon" src={icon} alt="" />}
        <span className="stats-tip-title-text">{title}</span>
      </div>
      {rows.filter(Boolean).map(([k, v]) => (
        <div className="stats-tip-row" key={k}><span>{k}</span><span>{v}</span></div>
      ))}
    </>
  )
}
