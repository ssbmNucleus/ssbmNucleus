// Pure helpers for the Menus tab's "Currently in MEX" card (MenuMode.jsx).

// Image URLs to try, best first: the snapshot copied into the project at
// install time (vault edits/deletes don't change it), then the vault URLs
// older records only have. The card falls through them on load errors and
// ends on a name placeholder instead of a broken image.
export function installedPreviewCandidates(mod) {
  if (!mod) return []
  const urls = [mod.snapshotUrl, mod.screenshotUrl, mod.imageUrl]
  return urls.filter((u, i) => typeof u === 'string' && u && urls.indexOf(u) === i)
}

// "12 of 26 icons installed" when an icon-grid install only partly landed.
export function partialIconText(mod) {
  const total = Number(mod?.icons_total) || 0
  const done = Array.isArray(mod?.icons_installed) ? mod.icons_installed.length : 0
  if (!total || !done || done >= total) return null
  return `${done} of ${total} icons installed`
}

// Slots /menus/installed?verify=<menu> reads from the project files, per menu.
export const CHECKED_SLOTS = {
  hud: ['hud:percent_font', 'hud:ready_go', 'hud:pause_screen'],
  css: ['css:icon_grid', 'css:doors', 'css:background'],
  sss: ['sss:background'],
}

// What a "Currently in MEX" card shows once the backend has compared the
// record with the project files (/menus/installed?verify=<menu>). kind:
// 'mod' (show the record), 'vanilla', or 'custom' (changed by something
// Nucleus did not record). Without a verification result the record is
// shown as before.
export function slotDisplay(installedMod, verification) {
  const v = verification && typeof verification === 'object' ? verification : null
  if (!v || !v.state) return { kind: installedMod ? 'mod' : 'vanilla', note: null }
  if (v.state === 'vanilla') {
    return {
      kind: 'vanilla',
      note: v.stale && installedMod
        ? `${installedMod.name} was installed here, but the project file is back to vanilla.`
        : null,
    }
  }
  if (v.state === 'custom') {
    if (installedMod && !v.stale) return { kind: 'mod', note: null }
    return {
      kind: 'custom',
      note: installedMod
        ? `The project file no longer matches ${installedMod.name}.`
        : 'Changed outside Nucleus (for example, a project made from an already-modded ISO).',
    }
  }
  return { kind: installedMod ? 'mod' : 'vanilla', note: null }
}
