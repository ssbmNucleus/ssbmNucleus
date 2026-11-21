// nucleus-replay — serves ssbmnucleus.net/replay/*
//
// Why a Worker and not a route in the website's React app: a share link's whole
// job is to be pasted into Discord, and an SPA unfurls as nothing. The tags have
// to be in the HTML the crawler receives, per share, which means server-rendered.
// Keeping it here also means the replay feature deploys on its own schedule
// instead of riding a full website deploy. A Workers route wins over the Pages
// project on the same hostname, so this claims /replay/* and nothing else.
//
// Routes:
//   /replay/<id>                 the page
//   /replay/<id>/combo/<n>       the page, opened on one combo
//   /replay/_d/<id>              meta + combos      (JSON, proxied)
//   /replay/_b/<id>              the game: raw .slp or frames file (gzip, proxied)
//   /replay/_c/<id>              conversions for a raw game (gzip, proxied)
//   /replay/_a/*                 static assets      (proxied to Pages)
//
// Everything the browser touches is same-origin. The signed R2 URL never leaves
// this Worker, so no bucket CORS rule stands between a viewer and a replay --
// that lesson cost three weeks of dead uploads once already.

const FN = "https://nttxcjrnqccogsibeqzz.supabase.co/functions/v1/vault-public";
const ASSETS = "https://nucleus-vault-3ds.pages.dev";
const SITE = "https://ssbmnucleus.net";
const ID_RE = /^[0-9a-z]{12}$/;

// The bundle is immutable for a given share (content-hash addressed), so it can
// be cached hard. The metadata can change -- a rename, a re-derive -- so it gets
// a short life instead.
const CACHE_BLOB = 86400;
const CACHE_META = 300;
const CACHE_ASSET = 86400;

const esc = (s) =>
  String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// The runtime's current (content-hashed) filename. Hashing exists because the
// asset proxy caches for a day: a fixed "replay.js" meant a deploy shipped and
// phones kept yesterday's runtime until the edge let go. The manifest is tiny
// and short-lived; the hashed file it names can cache forever without lying.
async function runtimeName() {
  try {
    const r = await fetch(`${ASSETS}/replay.manifest.json`, {
      cf: { cacheTtl: CACHE_META, cacheEverything: true },
    });
    if (r.ok) {
      const m = await r.json();
      if (typeof m.runtime === "string" && /^replay(\.[0-9a-f]{10})?\.js$/.test(m.runtime)) {
        return m.runtime;
      }
    }
  } catch { /* fall through */ }
  return "replay.js";
}

async function shareData(id) {
  const r = await fetch(`${FN}?id=${id}`, { cf: { cacheTtl: CACHE_META } });
  if (!r.ok) return null;
  return r.json();
}

// --- the view counter ------------------------------------------------------
// Counted here rather than in the runtime because a number the page reports
// about itself is a number anyone can type. The count is a write, and writes
// belong on the server side of the link.
//
// It is counted on the PAGE route only. /replay/_d, /_b and /_i are the same
// visit continuing -- data, bytes and the unfurl picture -- and counting them
// would multiply every view by four, plus once more for every crawler that
// fetches the thumbnail.

// How long one viewer stays "already counted". Long enough that a refresh, a
// reload after a stall, or opening two combos of the same match reads as one
// visit; short enough that coming back tomorrow counts again.
const VIEW_DEDUPE = 6 * 3600;
const VIEW_TIMEOUT = 2500;

// The unfurl crawlers are the reason this exists: every paste of a link into
// Discord fetches the page for its tags, and counting those would mean a link
// shows views nobody ever watched. Matching on the UA is crude and a crawler
// that lies gets counted -- but the ones that matter here all announce
// themselves.
const BOT_RE = /bot|crawler|spider|crawling|preview|facebookexternalhit|discord|slack|telegram|whatsapp|embed|curl|wget|headless|lighthouse|monitor/i;

// Identity for de-duplication only: a truncated hash of IP + user agent, never
// stored anywhere but a cache key, never written to the database. It is not a
// person -- everyone behind one NAT is one viewer, and a phone that changes
// towers is two.
async function viewerKey(id, request) {
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ua = request.headers.get("User-Agent") || "";
  const bytes = new TextEncoder().encode(`${id}\n${ip}\n${ua}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = [...new Uint8Array(digest)].slice(0, 10)
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  // A cache key must be a URL; this hostname is never resolved or fetched.
  return `https://view-dedupe.invalid/${id}/${hex}`;
}

// Two guards, both advisory, neither one infrastructure.
//
// RECENT is this isolate's memory: a bounded Map of viewer key -> the number it
// was last shown. It catches the case that actually happens -- somebody leaning
// on F5, or a page that reloads itself after a stall -- because those land in
// the same isolate seconds apart. Global mutable state in a Worker is normally
// a smell; this is a hash and an integer, never user data, capped, and losing
// it costs one extra count.
//
// The Cache API behind it is the same guard at colo scope, so two isolates on
// one edge agree. It is ALSO the one that cannot be exercised outside
// production: it is documented as inert on workers.dev, and `wrangler dev`
// throws "internal error" out of every cache.match(). Hence the layering --
// the guard that can be tested runs first, and the wider one is pure upside.
const RECENT = new Map();
const RECENT_MAX = 5000;

function remember(key, views) {
  RECENT.set(key, { at: Date.now(), views });
  // Map iterates in insertion order, so the front of it is the oldest. Trimming
  // in a batch keeps this off the hot path.
  if (RECENT.size > RECENT_MAX) {
    let drop = RECENT.size - RECENT_MAX + 500;
    for (const k of RECENT.keys()) { RECENT.delete(k); if (--drop <= 0) break; }
  }
}

// Returns the number to show, or null for "show nothing".
//
// Every failure path returns null. The counter is decoration and the replay is
// the product: a database that is down, a column that has not been added yet
// and a viewer whose bump timed out all render the same page, minus a number.
async function countView(id, request, ctx) {
  if (BOT_RE.test(request.headers.get("User-Agent") || "")) return null;

  let key;
  try {
    key = await viewerKey(id, request);
  } catch {
    return null;
  }

  // Both guards deliberately serve back the number this viewer was shown the
  // FIRST time rather than re-reading the live count. Re-reading would make a
  // refresh show a LOWER number than the load before it, because `get` is
  // edge-cached and lags the write -- a counter that goes backwards on F5 looks
  // broken in a way that being a few minutes stale does not.
  const recent = RECENT.get(key);
  if (recent && Date.now() - recent.at < VIEW_DEDUPE * 1000) return recent.views;

  let cache = null;
  try {
    cache = caches.default;
    const seen = await cache.match(key);
    if (seen) {
      const n = Number(await seen.text());
      if (Number.isFinite(n)) {
        remember(key, n);
        return n;
      }
    }
  } catch {
    // No usable cache. Then de-duplication is only as wide as this isolate --
    // a degradation, not a failure, and the number is still a number.
    cache = null;
  }

  let views = null;
  try {
    const r = await fetch(FN, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "view", id }),
      // Bounded so a slow database delays the page by at most this, instead of
      // holding the HTML hostage until something upstream gives up.
      signal: AbortSignal.timeout(VIEW_TIMEOUT),
    });
    if (r.ok) {
      const body = await r.json();
      if (typeof body.views === "number") views = body.views;
    }
  } catch { /* counted as "no number" */ }

  if (views !== null) {
    remember(key, views);
    if (cache) {
      ctx?.waitUntil?.(cache.put(key, new Response(String(views), {
        headers: { "Cache-Control": `max-age=${VIEW_DEDUPE}` },
      })).catch(() => {}));
    }
  }
  return views;
}

const plural = (n) => `${n.toLocaleString("en-US")} view${n === 1 ? "" : "s"}`;

// --- what a crawler sees ---------------------------------------------------
// Copied from frontend/src/shared/data/meleeNames.js -- the Worker cannot
// import it (separate deploy), so these two tables are the one duplication in
// the feature. Keep them in step with that file.
const CHARS = [
  "Captain Falcon", "Donkey Kong", "Fox", "Mr. Game & Watch", "Kirby", "Bowser", "Link", "Luigi",
  "Mario", "Marth", "Mewtwo", "Ness", "Peach", "Pikachu", "Ice Climbers",
  "Jigglypuff", "Samus", "Yoshi", "Zelda", "Sheik", "Falco", "Young Link",
  "Dr. Mario", "Roy", "Pichu", "Ganondorf",
];
const STAGES = {
  2: "Fountain of Dreams", 3: "Pokémon Stadium", 4: "Peach's Castle",
  5: "Kongo Jungle", 6: "Brinstar", 7: "Corneria", 8: "Yoshi's Story",
  9: "Onett", 10: "Mute City", 11: "Rainbow Cruise", 12: "Jungle Japes",
  13: "Great Bay", 14: "Hyrule Temple", 15: "Brinstar Depths",
  16: "Yoshi's Island", 17: "Green Greens", 18: "Fourside",
  19: "Mushroom Kingdom I", 20: "Mushroom Kingdom II", 22: "Venom",
  23: "Poké Floats", 24: "Big Blue", 25: "Icicle Mountain", 26: "Icetop",
  27: "Flat Zone", 28: "Dream Land N64", 29: "Yoshi's Island N64",
  30: "Kongo Jungle N64", 31: "Battlefield", 32: "Final Destination",
};

function describe(data, comboN) {
  const g = (data && data.game) || {};
  const ps = g.players || [];
  const names = ps.map((p) => CHARS[p.character] || "Fighter");
  const who = ps.map((p) => p.code || p.name).filter(Boolean);
  const stage = STAGES[g.stage] || "Melee";

  let title = names.length === 2 ? `${names[0]} vs ${names[1]}` : "Melee replay";
  if (who.length === ps.length && who.length) {
    title = ps.map((p, i) => `${names[i]} (${who[i]})`).join(" vs ");
  }

  const combos = (data && data.combos) || [];
  const c = comboN >= 1 && comboN <= combos.length ? combos[comboN - 1] : null;
  if (c) {
    const hits = (c.moves || []).length || c.hits || 0;
    // Lead with the number that makes someone click. A kill is the point of the
    // clip when there is one, so it is said plainly rather than left implied.
    title = `${hits}-hit combo for ${Math.round(c.damage || 0)}%`
      + `${c.did_kill ? " and the stock" : ""} on ${stage} — ${title}`;
  }
  // Deliberately NO description: the unfurl is the title and the picture.
  // Every tagline draft under it read as ad copy and diluted both.
  return { title };
}

function page(id, comboN, data, runtime, views) {
  const { title } = describe(data, comboN);
  const canonical = comboN ? `${SITE}/replay/${id}/combo/${comboN}` : `${SITE}/replay/${id}`;
  const cfg = JSON.stringify({ id, combo: comboN || null }).replace(/</g, "\\u003c");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#06150c">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="video.other">
<meta property="og:site_name" content="SSBM Nucleus">
<meta property="og:title" content="${esc(title)}">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${SITE}/replay/_i/${id}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:image" content="${SITE}/replay/_i/${id}">
<!-- Every relative asset the runtime asks for (packs/, stock/, charmaps.json)
     resolves through the proxy, so the runtime needs no idea it is not on the
     vault's own origin. -->
<base href="/replay/_a/">
<style>
  /* Ripped from the vault app's template: same tokens, same chrome. Mobile is
     the app's full-bleed player; from 760px up the player sits in a centered
     panel so a widescreen window does not become one giant canvas. */
  * { box-sizing: border-box; margin: 0; -webkit-tap-highlight-color: transparent; }
  html, body { background: #06150c; scrollbar-color: #203c2a #06150c; }
  body {
    color: #f5f5f5; display: flex; flex-direction: column; align-items: center;
    min-height: 100dvh;
    font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
  }
  .shell { width: 100%; display: flex; flex-direction: column; }
  header {
    display: flex; align-items: center; gap: 10px;
    padding: calc(10px + env(safe-area-inset-top, 0px)) 14px 10px;
  }
  .who { flex: 1 1 auto; min-width: 0; }
  #title {
    font-size: 15px; font-weight: 700;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  #subtitle {
    font-size: 11px; color: #87958c; margin-top: 2px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .mcard-loading { font-size: 14px; font-weight: 700; padding: 4px 0; }
  /* the match card, same classes matchcard.js emits for the app */
  .dsum { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px; }
  .dsum-side { display: flex; align-items: center; gap: 8px; min-width: 0; }
  /* mirrored, not merely right-justified: char icons at the outer edges, rank
     then W/L pairing off symmetrically around the vs */
  .dsum-side--r { flex-direction: row-reverse; }
  .dsum-side--r .dsum-id { align-items: flex-end; text-align: right; }
  .dsum-rank { width: 24px; height: 24px; flex: none; }
  .dsum-rank img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .dsum-norank { display: grid; place-items: center; width: 100%; height: 100%;
                 color: #5c6b62; font-size: 13px; }
  a.dsum-name { color: inherit; text-decoration: none; }
  a.dsum-name:hover { text-decoration: underline; }
  .dsum-id { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
  .dsum-name { font-weight: 600; font-size: 13px; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }
  .dsum-tag { font-family: ui-monospace, Menlo, Consolas, monospace;
              font-size: 10px; color: #87958c; }
  .pl-stocks { display: flex; gap: 1px; height: 9px; margin-top: 2px; }
  .pl-stocks img { width: 9px; height: 9px; image-rendering: pixelated; }
  .vs-mid { color: #5c6b62; font-size: 10.5px; flex: none; }
  .result { display: inline-grid; place-items: center; flex: 0 0 22px; height: 22px;
            border-radius: 7px; font-size: 10px; font-weight: 800; }
  .result--win  { color: #4ade80; background: rgba(74, 222, 128, 0.15); }
  .result--loss { color: #ff4757; background: rgba(255, 71, 87, 0.15); }
  .row-meta { display: flex; align-items: center; gap: 6px;
              margin-top: 6px; padding-top: 6px; border-top: 1px solid #203c2a;
              font-size: 10.5px; color: #87958c; }
  .stage-ico { width: 22px; height: 16px; object-fit: cover; border-radius: 4px; flex: none; }
  .row-meta .stg { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .row-meta .dot { color: #5c6b62; }
  .row-meta .grow { flex: 1 1 auto; }
  .row-meta .dur { font-family: ui-monospace, Menlo, Consolas, monospace; }
  /* top-right stack: the count sits above the CTA rather than beside it, so it
     costs the match card no width on a phone -- the card is already the first
     thing to ellipsize there. */
  .topr {
    flex: 0 0 auto; display: flex; flex-direction: column;
    align-items: flex-end; gap: 6px;
  }
  /* Same muted grey and mono digits as .row-meta's duration: this is a fact
     about the replay, in the voice the page already uses for facts about the
     replay -- not a badge competing with the download button under it. */
  .views {
    display: flex; align-items: center; gap: 5px;
    font-size: 11px; color: #87958c;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    white-space: nowrap;
  }
  .views svg { flex: none; opacity: .85; }
  .get {
    flex: 0 0 auto; font-size: 12px; font-weight: 600; text-decoration: none;
    color: #0b1f13; background: #57d98a; padding: 8px 14px; border-radius: 999px;
  }
  .wrap {
    position: relative; display: flex; height: 52dvh;
    background: #0a0c12; border: 1px solid #203c2a; border-left: 0; border-right: 0;
    overflow: hidden;
  }
  #stage { flex: 1 1 auto; min-height: 0; width: 100%; }
  #pstatus {
    position: absolute; left: 0; right: 0; top: 50%; text-align: center;
    font-size: 12px; color: #87958c; pointer-events: none;
  }
  #combos { padding: 8px 14px; }
  .chiprow { display: flex; gap: 6px; padding: 2px 0 10px; }
  .ccombo {
    flex: 0 0 auto; font-size: 12px; color: #cfe6d8; text-decoration: none;
    background: #16281c; border: 1px solid #203c2a; border-radius: 999px;
    padding: 6px 12px; white-space: nowrap;
  }
  .ccombo.on { background: #57d98a; color: #0b1f13; border-color: #57d98a; }
  /* the app's two-column combo layout, tokens inlined from its template */
  .dcombo-cols { display: flex; gap: 8px; align-items: flex-start; }
  .dcombo-col { flex: 1 1 0; min-width: 0; }
  .dcombo-colhead {
    display: flex; align-items: center; gap: 6px;
    padding: 2px 4px 6px; font-size: 12px; font-weight: 600; color: #b6c2ba;
  }
  .dcombo-colhead img { width: 18px; height: 18px; image-rendering: pixelated; }
  .dcombo-colhead span { flex: 1 1 auto; min-width: 0;
                         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dcombo-colhead b {
    font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
    font-size: 11px; font-weight: 400; color: #5c6b62;
  }
  .dcombo-none { padding: 4px; font-size: 11px; color: #5c6b62; }
  .dcombo-cell {
    position: relative; display: block; text-decoration: none;
    padding: 8px; margin-bottom: 6px; border-radius: 12px;
    background: #12271a; border: 1px solid #203c2a;
  }
  .dcombo-cell:hover { background: #1a3424; }
  .dcombo-cell.is-active { background: rgba(167, 139, 250, 0.15); border-color: #a78bfa; }
  .dcombo-top { display: flex; align-items: baseline; gap: 6px; }
  .dcombo-dmg {
    font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
    font-weight: 700; font-size: 15px; color: #a78bfa;
  }
  .dcombo-time {
    font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
    font-size: 11px; color: #87958c;
  }
  .dcombo-sub { display: block; margin-top: 2px; font-size: 11px; color: #87958c; }
  .dcombo-badges { display: flex; gap: 4px; margin-top: 5px; }
  .kill-badge {
    font-size: 9px; font-weight: 800; letter-spacing: .07em;
    color: #06150c; background: #ff4757; padding: 2px 6px; border-radius: 4px;
  }
  .true-badge {
    font-size: 9px; font-weight: 800; letter-spacing: .07em;
    color: #06150c; background: #38e07c; padding: 2px 6px; border-radius: 4px;
  }
  .transport {
    position: relative;   /* anchors the overlays menu above its button */
    display: flex; align-items: center; gap: 12px; padding: 10px 14px;
  }
  .ovlmenu {
    position: absolute; right: 40px; bottom: 46px; z-index: 5;
    min-width: 160px; padding: 6px;
    background: #0f2015; border: 1px solid #203c2a; border-radius: 12px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, .45);
    display: flex; flex-direction: column; gap: 2px;
  }
  /* display:flex above would otherwise beat the [hidden] UA default and the
     "closed" menu stays painted as an empty box */
  .ovlmenu[hidden] { display: none; }
  .ovlrow {
    display: flex; align-items: center; gap: 10px; width: 100%;
    padding: 8px 10px; border: 0; border-radius: 9px; background: none;
    color: #cfe6d8; text-align: left; cursor: pointer;
  }
  .ovlrow:hover { background: #16281c; }
  .ovlrow-txt { flex: 1 1 auto; }
  .ovlrow-txt b { font-size: 12.5px; font-weight: 600; }
  .ovlrow-check {
    flex: 0 0 auto; width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #2c4a36; position: relative;
  }
  .ovlrow.on .ovlrow-check { background: #57d98a; border-color: #57d98a; }
  .ovlrow.on .ovlrow-check::after {
    content: ''; position: absolute; left: 4.5px; top: 1.5px;
    width: 4px; height: 8px;
    border: solid #0b1f13; border-width: 0 2px 2px 0; transform: rotate(41deg);
  }
  .transport input[type="range"] {
    flex: 1 1 auto; min-width: 0; height: 36px;
    -webkit-appearance: none; appearance: none; background: transparent;
  }
  .transport input[type="range"]::-webkit-slider-runnable-track {
    height: 4px; border-radius: 2px;
    background: linear-gradient(90deg, #57d98a var(--p, 0%), #22331f var(--p, 0%));
  }
  .transport input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 14px; height: 14px; margin-top: -5px;
    border-radius: 50%; background: #57d98a;
  }
  .transport input[type="range"]::-moz-range-track {
    height: 4px; border-radius: 2px; background: #22331f;
  }
  .transport input[type="range"]::-moz-range-thumb {
    width: 14px; height: 14px; border: 0; border-radius: 50%; background: #57d98a;
  }
  #play {
    flex: 0 0 auto; width: 40px; height: 40px; border: 0; border-radius: 50%;
    background: #16281c; color: #f5f5f5; display: grid; place-items: center;
    cursor: pointer;
  }
  .tgrp { display: flex; align-items: center; gap: 4px; }
  .tbtn {
    flex: 0 0 auto; width: 32px; height: 32px; border: 0; border-radius: 50%;
    background: none; color: #87958c; display: grid; place-items: center;
    cursor: pointer;
  }
  .tbtn:hover { color: #f5f5f5; }
  .tbtn.on { color: #57d98a; }
  .convtl {
    display: block; width: calc(100% - 28px); height: 26px; margin: 0 14px 8px;
    border-radius: 7px; background: #12271a; border: 1px solid #203c2a;
    box-sizing: border-box; touch-action: none;
  }
  footer {
    padding: 4px 14px calc(12px + env(safe-area-inset-bottom, 0px));
    font-size: 11px; color: #87958c;
  }
  footer a { color: #57d98a; text-decoration: none; }
  @media (min-width: 760px) {
    body { align-items: center; }
    .shell { max-width: 1060px; padding: 12px 20px 0; }
    header { padding: 10px 2px 12px; }
    /* the card reads as one object; unbounded it scatters its two sides
       across the whole shell with the vs marooned in the middle */
    .who { max-width: 460px; }
    /* ...which leaves the header's remaining width unclaimed, so without this
       the corner stack sits marooned against the card instead of over the
       player's right edge. Below 760px the card already grows and pins it. */
    .topr { margin-inline-start: auto; }
    #title { font-size: 18px; }
    #subtitle { font-size: 12px; margin-top: 3px; }
    .wrap {
      height: auto; aspect-ratio: 16 / 10;
      max-height: calc(100dvh - 240px); min-height: 320px;
      border: 1px solid #203c2a; border-radius: 12px;
      /* height-capped, so width follows the ratio -- centre the leftover */
      margin-inline: auto; width: 100%;
    }
    #combos { padding: 0 2px 8px; }
    .transport { padding: 10px 0; }
    .convtl { width: 100%; margin: 0 0 10px; }
    footer { padding: 4px 2px 16px; }
    .kbd { display: inline; }
  }
  .kbd { display: none; }
</style>
</head>
<body>
<div class="shell">
<header>
  <div class="who" id="mcard">
    <div class="mcard-loading">${esc(title)}</div>
  </div>
  <div class="topr">
    ${typeof views === "number" ? `<div class="views" aria-label="${esc(plural(views))}">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
      <span>${esc(plural(views))}</span>
    </div>` : ""}
    <a class="get" href="${SITE}/download">Get Nucleus</a>
  </div>
</header>
<div class="wrap">
  <canvas id="stage"></canvas>
  <div id="pstatus">loading…</div>
</div>
<div class="transport">
  <div class="tgrp">
    <button id="stepb" class="tbtn" aria-label="Step back one frame"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="5.8" y="7" width="2.2" height="10" rx="1"/><path d="M17 7.4v9.2a1 1 0 0 1-1.55.83l-6.9-4.6a1 1 0 0 1 0-1.66l6.9-4.6A1 1 0 0 1 17 7.4z"/></svg></button>
    <button id="play" aria-label="Play"></button>
    <button id="stepf" class="tbtn" aria-label="Step forward one frame"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M7 7.4v9.2a1 1 0 0 0 1.55.83l6.9-4.6a1 1 0 0 0 0-1.66l-6.9-4.6A1 1 0 0 0 7 7.4z"/><rect x="16" y="7" width="2.2" height="10" rx="1"/></svg></button>
  </div>
  <input id="seek" type="range" min="0" max="1" value="0" aria-label="Seek">
  <button id="ovl" class="tbtn" aria-label="Overlays"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 8h10M18 8h2M4 16h4M12 16h8"/><circle cx="16" cy="8" r="2"/><circle cx="10" cy="16" r="2"/></svg></button>
  <button id="fs" class="tbtn" aria-label="Fullscreen"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/></svg></button>
</div>
<canvas id="tl" class="convtl" hidden></canvas>
<div id="combos" hidden></div>
<footer>
  Shared with <a href="${SITE}">SSBM Nucleus</a><span class="kbd"> ·
  Space plays, arrows step frames</span>
</footer>
</div>
<script>window.__REPLAY = ${cfg}</script>
<script src="/replay/_a/${runtime}"></script>
</body>
</html>`;
}

async function proxy(url, ttl, extra) {
  const r = await fetch(url, { cf: { cacheTtl: ttl, cacheEverything: true } });
  const h = new Headers(r.headers);
  h.set("Cache-Control", `public, max-age=${ttl}`);
  h.delete("set-cookie");
  for (const [k, v] of Object.entries(extra || {})) h.set(k, v);
  return new Response(r.body, { status: r.status, headers: h });
}

const notFound = (msg) =>
  new Response(msg, { status: 404, headers: { "Content-Type": "text/plain" } });

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);   // ["replay", ...]
    if (parts[0] !== "replay") return notFound("not found");

    // /replay/_a/<path> — static assets from the vault's Pages origin.
    if (parts[1] === "_a") {
      const rest = parts.slice(2).join("/");
      if (!rest) return notFound("not found");
      return proxy(`${ASSETS}/${rest}`, CACHE_ASSET);
    }

    // /replay/_d/<id> — meta + combos, minus the signed URL. The browser has no
    // use for it (the bytes come back through _b) and publishing a credentialed
    // URL to every viewer would outlive the page they got it from.
    if (parts[1] === "_d") {
      const id = parts[2];
      if (!ID_RE.test(id || "")) return notFound("bad link");
      const data = await shareData(id);
      if (!data || data.error) return notFound("no such link");
      delete data.url;
      // Same for the conversions sidecar: the page only needs to know whether
      // /_c has anything, never the signed URL itself.
      data.has_conv = Boolean(data.conv_url);
      delete data.conv_url;
      return new Response(JSON.stringify(data), {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `public, max-age=${CACHE_META}`,
          // The whole point of a share is that the data is public, so there is
          // nothing to protect with an origin check -- and allowing it means the
          // vault app can embed a public clip later without a second endpoint.
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // /replay/_i/<id> — the unfurl thumbnail, drawn by the sharer's client at
    // share time. Absent object -> R2 404 passes through, and the crawler just
    // shows a text-only card.
    if (parts[1] === "_i") {
      const id = parts[2];
      if (!ID_RE.test(id || "")) return notFound("bad link");
      const data = await shareData(id);
      if (!data || !data.thumb_url) return notFound("no such link");
      return proxy(data.thumb_url, CACHE_META, { "Content-Type": "image/png" });
    }

    // /replay/_c/<id> — a raw replay's conversions sidecar (gzip JSON). Games
    // uploaded before raw replays carry conversions inside their frames file.
    if (parts[1] === "_c") {
      const id = parts[2];
      if (!ID_RE.test(id || "")) return notFound("bad link");
      const data = await shareData(id);
      if (!data || !data.conv_url) return notFound("no such link");
      return proxy(data.conv_url, CACHE_BLOB, {
        "Content-Type": "application/gzip",
        "Access-Control-Allow-Origin": "*",
      });
    }

    // /replay/_b/<id> — the game: the raw .slp (gzip) when the vault has it,
    // else the derived frames file. The page tells them apart by their bytes.
    if (parts[1] === "_b") {
      const id = parts[2];
      if (!ID_RE.test(id || "")) return notFound("bad link");
      const data = await shareData(id);
      if (!data || !data.url) return notFound("no such link");
      return proxy(data.url, CACHE_BLOB, {
        "Content-Type": "application/gzip",
        "Access-Control-Allow-Origin": "*",
      });
    }

    // /replay/<id>[/combo/<n>]
    const id = parts[1];
    if (!ID_RE.test(id || "")) {
      return new Response("This is not a Nucleus replay link.", {
        status: 404, headers: { "Content-Type": "text/plain" },
      });
    }
    let comboN = 0;
    if (parts[2] === "combo") comboN = Number(parts[3]) || 0;

    // The page is rendered from the share's own data so the unfurl is real. A
    // dead link must answer 404 rather than a page that says "loading" forever.
    // The count runs alongside the two fetches the page already needed, not
    // after them, so it costs the render nothing it was not already waiting on.
    const [data, runtime, counted] = await Promise.all([
      shareData(id), runtimeName(), countView(id, request, ctx),
    ]);
    if (!data || data.error) {
      return new Response("This replay link has expired or was deleted.", {
        status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    // Prefer the total the bump just returned -- it includes this visit and is
    // to the second. `get`'s copy is the fallback for a skipped or failed bump;
    // it is edge-cached, so it can be minutes behind.
    const views = typeof counted === "number" ? counted
      : (typeof data.views === "number" ? data.views : null);

    return new Response(page(id, comboN, data, runtime, views), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        // Unchanged, and load-bearing for the counter: a browser serving the
        // page from its own cache never reaches this Worker, which is one more
        // reason a refresh does not inflate the number.
        "Cache-Control": `public, max-age=${CACHE_META}`,
      },
    });
  },
};
