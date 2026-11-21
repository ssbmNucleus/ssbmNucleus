// Feature gates for surfaces that are built but not publicly released.
//
// nucleOME shipped in 0.7.0 — the flag stays as the single choke point for the
// mode toggle (App.jsx), the wordmark affordance (BrandWordmark.jsx), and the
// Patreon + start.gg rows in Settings (AccountSection.jsx), in case a future
// build ever needs to gate it again. Premium (Patreon) gating is a separate
// layer and is unaffected by this flag.
export const NUCLEOME_ENABLED = true

// Trailer captures film against a dev Vite server but must show the RELEASED
// surface set — unreleased tabs in public footage would advertise features
// that aren't shipping. Capture scripts set VITE_SHIP_GATES=1 on the Vite
// they spawn (the trailer repo's capture-nucleome.mjs); normal dev keeps both.
const SHIP_GATES = import.meta.env.VITE_SHIP_GATES === '1'

export const ASSISTANT_ENABLED = (import.meta.env.DEV || import.meta.env.VITE_ASSISTANT_PREVIEW === '1') && !SHIP_GATES

// The two dev-only pages below are also closed when their files are not in the
// checkout: the public source drop (tools/public_drop.py) leaves the unreleased
// features out, and a clone of it runs as dev. import.meta.glob matches nothing
// there. Each glob sits after `import.meta.env.DEV &&`, so a production build
// folds it away with the rest of the expression and adds no chunk.

// The Combo Video maker stayed behind when nucleOME shipped in 0.7.0 — it is
// unfinished and lands in a later update. Gates the Combos-page entry point;
// the backend half is NUCLEUS_COMBO_VIDEO=0 in electron/main.js, which 404s
// /api/nucleome/combo-video in packaged builds.
export const COMBO_VIDEO_ENABLED = import.meta.env.DEV && !SHIP_GATES
  && Object.keys(import.meta.glob('../../tracker/video/ComboVideoPage.jsx')).length > 0

// Randall (the Tracker coach) is enabled in development only. An assistant
// preview package opens the assistant chat, not the coach. Gates the tab, the CoachPage bundle
// chunk (NucleomeApp.jsx folds the import), and the stored-tab restore
// (App.jsx). The backend half is NUCLEUS_RANDALL=0 in electron/main.js, which
// 404s /api/nucleome/coach/*. The baseline packs stay bundled either way —
// the Stats page's deep-stats panels read them too.
export const RANDALL_ENABLED = import.meta.env.DEV && !SHIP_GATES
  && Object.keys(import.meta.glob('../../randall/coach/CoachPage.jsx')).length > 0
