// Record launch mode: strips dev chrome and personal UI from the app so
// trailer/screenshot captures look like a clean stock install. Currently
// hides the header version tag, the DEV tier chip, and the Account and
// Update settings sections.
//
// Enable with `run.bat --record` (sets VITE_RECORD_MODE=1 for the dev
// server) or, in a running build, via
// `localStorage.setItem('nucleus-record-mode', '1')` + reload.
export const RECORD_MODE =
  import.meta.env.VITE_RECORD_MODE === '1' ||
  (typeof localStorage !== 'undefined' &&
    localStorage.getItem('nucleus-record-mode') === '1')
