#!/usr/bin/env node
// Phone-app screenshots for the guide, at phone size, WITHOUT a device token.
//
// The live app at tracker.ssbmnucleus.net runs its own real code; only the
// vault-read calls are answered locally, from the same 60-game sample library
// the desktop Tracker shots use (docs/guide/scripts/phone_payload.py). So the phone
// shots show the same games as the desktop shots, no credential is minted, and
// nothing reaches anyone's cloud account.
//
//   node docs/guide/scripts/capture-phone.mjs [--site https://tracker.ssbmnucleus.net]
//
// GUIDE_STARTGG_SLUG seeds the Tourney tab, which is public (startgg-proxy
// takes no token) and is therefore the one tab that talks to the real network.
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const NUCLEUS = resolve(__dirname, "..", "..", "..", "app");  // the app/ folder
const GUIDE_DIR = resolve(__dirname, "..");               // docs/guide
const { chromium } = createRequire(join(NUCLEUS, "package.json"))("playwright-core");
const OUT = join(GUIDE_DIR, "img");
const RAW = join(OUT, "_raw");
mkdirSync(RAW, { recursive: true });
const PYTHON = existsSync(join(NUCLEUS, "venv", "Scripts", "python.exe"))
  ? join(NUCLEUS, "venv", "Scripts", "python.exe") : "python";

const argValue = (f, d) => { const i = process.argv.indexOf(f); return i >= 0 ? process.argv[i + 1] : d; };
const SITE = argValue("--site", "https://tracker.ssbmnucleus.net").replace(/\/$/, "");
const DATA_PATH = join(GUIDE_DIR, ".capture", "phone-data.json");

if (!existsSync(DATA_PATH)) {
  spawnSync(PYTHON, [join(__dirname, "phone_payload.py"), DATA_PATH], { stdio: "inherit" });
}
const DATA = JSON.parse(readFileSync(DATA_PATH, "utf8"));
console.log(`[phone] stub library: ${DATA.games.length} games, ${DATA.combos.length} combos`);

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "POST,OPTIONS",
};

// The subset of vault-read the browse surfaces actually call. Filters mirror
// the edge function's, because the tab headers count what the list shows.
function vaultRead(body) {
  if (body.action === "list") return { games: DATA.games, next_before: null };
  if (body.action === "ranks") {
    const out = {};
    for (const code of body.codes || []) if (DATA.ranks[code]) out[code] = DATA.ranks[code];
    return { ranks: out };
  }
  if (body.action === "prefs-get") return { prefs: {} };
  if (body.action === "prefs-set") return { ok: true };
  if (body.action === "combos") {
    const f = body.filters || {};
    const mine = new Set(DATA.codes.map((c) => c.toUpperCase()));
    let rows = DATA.combos.filter((c) => {
      if (body.game_id != null && c.game_id !== body.game_id) return false;
      if (f.min_moves != null && (c.moves || []).length < f.min_moves) return false;
      if (f.min_damage != null && c.damage < f.min_damage) return false;
      if ((f.kills_only ?? body.kills_only) && !c.did_kill) return false;
      if (f.did_kill && !c.did_kill) return false;
      if (f.direction === "received") return mine.has((c.opp_code || "").toUpperCase());
      if (f.direction === "mine") return mine.has((c.code || "").toUpperCase());
      return true;
    });
    const key = { damage: "damage", moves: "hits", date: "id", percent: "end_percent" }[body.sort || "damage"] || "damage";
    const asc = body.dir === "asc";
    rows = rows.slice().sort((a, b) => (asc ? 1 : -1) * ((a[key] ?? 0) - (b[key] ?? 0) || a.id - b.id));
    if (body.count_only === true) return { total: rows.length };
    const offset = Number(body.offset) || 0;
    const limit = Number(body.limit) || 50;
    return { combos: rows.slice(offset, offset + limit) };
  }
  return { ok: true };
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
});

// A token the app never sends anywhere real: every vault-read is answered below.
await page.addInitScript(([codes, slug]) => {
  localStorage.setItem("nucleus.vault.token", "nvt_guide_capture_stub");
  localStorage.setItem("nucleus.vault.generation", "1");
  localStorage.setItem("nucleus.vault.codes", JSON.stringify(codes));
  if (slug) localStorage.setItem("nucleus.startgg.slug", slug);
}, [DATA.codes, process.env.GUIDE_STARTGG_SLUG || ""]);

await page.route("**/functions/v1/vault-read", async (route) => {
  const req = route.request();
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
  let body = {};
  try { body = JSON.parse(req.postData() || "{}"); } catch { /* keep {} */ }
  route.fulfill({ status: 200, headers: { ...CORS, "content-type": "application/json" },
                  body: JSON.stringify(vaultRead(body)) });
});

const shot = async (id, { settle = 1200 } = {}) => {
  await page.waitForTimeout(settle);
  await page.screenshot({ path: join(RAW, `${id}.png`) });
  writeFileSync(join(OUT, `${id}.json`), JSON.stringify({
    viewport: { w: 390, h: 844, dpr: 2 }, marks: [], crop: null,
    captured: new Date().toISOString().slice(0, 10), source: page.url(),
  }, null, 2));
  console.log(`[phone]   ✓ ${id}`);
};

const tab = async (name) => {
  await page.getByRole("tab", { name }).click({ timeout: 15000 });
  await page.waitForTimeout(1200);
};

try {
  await page.goto(SITE, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForSelector(".pl-char", { timeout: 60000 });
  await shot("08-mobile-games", { settle: 2500 });

  await tab(/combos/i);
  await page.waitForTimeout(3000);
  await shot("08-mobile-combos", { settle: 2500 });

  await tab(/stats/i);
  await shot("08-mobile-stats", { settle: 3000 });

  if (process.env.GUIDE_STARTGG_SLUG) {
    await tab(/tourney/i);
    // start.gg is crawled live through the public proxy; the first sync of a
    // busy profile is slow, so wait for real rows rather than a fixed delay.
    await page.waitForSelector(".set-row, .section", { timeout: 180000 });
    await shot("08-mobile-tourney", { settle: 4000 });
  }
} catch (err) {
  console.error("[phone] failed:", err.message.split("\n")[0]);
  process.exitCode = 1;
} finally {
  await browser.close();
}
spawnSync(PYTHON, [join(__dirname, "annotate.py"), OUT], { stdio: "inherit" });
