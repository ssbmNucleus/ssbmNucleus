import { lazy, Suspense } from 'react'
import { COMBO_VIDEO_ENABLED, RANDALL_ENABLED } from '../shared/config/features'
import { NUCLEOME_TABS } from './NucleomeTabs'
const CombosPage = lazy(() => import('./combos/CombosPage'))
// A gated page, loaded through import.meta.glob: a public source checkout
// leaves its file out (tools/public_drop.py), the glob then matches nothing and
// the page renders nothing, where a plain import() would not even resolve.
const gatedPage = (found) => {
  const load = Object.values(found)[0]
  return load ? lazy(load) : () => null
}
// The Combo Video maker is gated out of packaged builds (unfinished — later
// update). The literal import.meta.env.DEV condition (the same value
// COMBO_VIDEO_ENABLED carries) lets Rollup constant-fold the dynamic import
// away in `vite build`, so the unreleased page's code is not even PRESENT in
// the shipped installer — not just unreachable.
const ComboVideoPage = import.meta.env.DEV
  ? gatedPage(import.meta.glob('./video/ComboVideoPage.jsx'))
  : () => null
// Include the coach in development and designated Randall preview installers.
// Normal release builds still fold this chunk away.
const CoachPage = RANDALL_ENABLED
  ? gatedPage(import.meta.glob('../randall/coach/CoachPage.jsx'))
  : () => null
const ReplaysPage = lazy(() => import('./replays/ReplaysPage'))
const StatsPage = lazy(() => import('./stats/StatsPage'))
const TournamentsPage = lazy(() => import('./tournaments/TournamentsPage'))
import './nucleome.css'
import StatsLoading from './stats/StatsLoading'
import ComboLoading from './combos/ComboLoading'

// nucleOME — the replay-analysis / coaching sibling app. This is the v1
// SHELL only: top-level navigation + placeholder pages. It shares the app
// window chrome (header, brand toggle) with nucleus mode; the header itself
// lives in App.jsx, which renders <NucleomeTabs/> next to the shared brand
// and <NucleomeApp/> as the content area.

// Everything except Coach — these tabs are cheap and stateless enough to
// mount on demand.
function OtherTab({ tab, settingsContent, onTabChange }) {
  // Settings is the real, shared nucleus Settings component (passed in from
  // App.jsx so both modes edit the same config); other tabs are v1 shells.
  if (tab.id === 'settings' && settingsContent) {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">{settingsContent}</div>
      </main>
    )
  }

  // nucleOME monetization. The 0.7.0 launch rule was "see everything you have,
  // pay to do anything with it". That is over: everything already SHIPPED on
  // the desktop is free — Replays, Combos, Stats, Watch Lite, Watch with mods,
  // vault sync and share links. What is still paid: the phone (the $5 tier,
  // enforced server-side in resolveOwner's device-token branch) and Randall,
  // which is unreleased anyway and keeps its own gate below.
  //
  // Signing in with Patreon is still needed for anything that touches our
  // servers — sync and share — but a FREE $0 account satisfies it. The link
  // exists so users are countable and bannable, not to charge them.
  if (tab.id === 'combos') {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">
          <Suspense fallback={<ComboLoading />}><CombosPage /></Suspense>
        </div>
      </main>
    )
  }

  if (tab.id === 'combovideo' && COMBO_VIDEO_ENABLED) {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">
          <Suspense fallback={null}>
            <ComboVideoPage />
          </Suspense>
        </div>
      </main>
    )
  }

  if (tab.id === 'replays') {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">
          <Suspense fallback={null}><ReplaysPage /></Suspense>
        </div>
      </main>
    )
  }

  // Tournaments is FREE, always — it's the player's own public start.gg
  // record, so it never sits behind a premium gate (start.gg ToS: their data
  // isn't something we get to sell).
  if (tab.id === 'tournaments') {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">
          <Suspense fallback={<div className="stats-page" role="status">Loading tournaments…</div>}>
            <TournamentsPage
              onGoToSettings={onTabChange ? () => onTabChange('settings') : undefined}
            />
          </Suspense>
        </div>
      </main>
    )
  }

  if (tab.id === 'stats') {
    return (
      <main className="app-content mode-enter">
        <div className="app-panel app-panel--scroll">
          <Suspense fallback={<StatsLoading />}><StatsPage /></Suspense>
        </div>
      </main>
    )
  }

  return (
    <main className="app-content mode-enter">
      <div className="app-panel app-panel--scroll">
        {/* key remounts the card per tab so the entrance animation replays */}
        <div className="nucleome-page" key={tab.id}>
          <div className="nucleome-page-card">
            <span className="nucleome-page-kicker">Nucleus Stats</span>
            <h2 className="nucleome-page-title">{tab.label}</h2>
            <p className="nucleome-page-blurb">{tab.blurb}</p>
            <span className="nucleome-page-soon">Coming soon</span>
          </div>
        </div>
      </div>
    </main>
  )
}

export default function NucleomeApp({ activeTab, onTabChange, settingsContent }) {
  const tab = NUCLEOME_TABS.find((entry) => entry.id === activeTab) || NUCLEOME_TABS[0]
  const coachActive = RANDALL_ENABLED && tab.id === 'coach'

  // Coach stays mounted even when another tab is active — a coach turn takes
  // 10-50s of streaming tool calls, and leaving mid-answer must NOT throw that
  // turn away. So we hide it (display:none) instead of unmounting; the fetch
  // keeps streaming and the transcript is intact when you return. In builds
  // where Randall is gated off the pane never mounts at all.
  return (
    <>
      {RANDALL_ENABLED && (
        <main
          className={`app-content${coachActive ? ' mode-enter' : ' app-content--hidden'}`}
          aria-hidden={!coachActive}
        >
          <div className="app-panel app-panel--fill">
            <Suspense fallback={null}>
              <CoachPage active={coachActive} onOpenSettings={() => onTabChange?.('settings')} />
            </Suspense>
          </div>
        </main>
      )}
      {!coachActive && <OtherTab tab={tab} settingsContent={settingsContent} onTabChange={onTabChange} />}
    </>
  )
}
