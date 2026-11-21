// Watch Lite paints its HUD and panels as HTML strings. Replay text (player tags and connect codes, move names) is
// data from a .slp anyone can make, so it is escaped before it goes into innerHTML, and ids in URLs are encoded.
const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ENTITIES[c])

export const urlId = (v) => encodeURIComponent(String(v ?? 0))
