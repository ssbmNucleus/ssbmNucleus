// nucleus-bugreport — private bug-report intake for the SSBM Nucleus desktop app.
//
// Flow (the desktop's Flask backend is the only caller):
//   1. POST /bugreport            JSON meta → version gate, rate limit, slot id
//   2. PUT  /bugreport/:id/zip    raw zip body, streamed straight into R2
//      → meta.json written, Discord embed posted to a PRIVATE channel with a
//        signed download link (the zip itself is attached when small).
//      A delivery receipt (`d/<id>`) outlives the slot, so re-uploading a
//      STORED report answers 200 again (`already_stored`) instead of 404: a
//      client whose reply was lost can tell "delivered" from "slot expired".
//   3. GET  /bugreport/:id/zip|meta?d=&exp=&sig=   admin-only, HMAC-signed.
//
// Report kinds (`kind` in the POST meta; absent = "bug", so every client
// released before kinds existed keeps working unchanged):
//   bug             Settings -> Bug report (logs zip)
//   chat            "Report this chat" from Randall (desktop mods/tracker or the
//                   mobile vault); carries a small `chat` block for the ping.
//                   The mobile client posts cross-origin, so /bugreport answers
//                   CORS preflights, and platform "mobile" is accepted for chat
//                   reports only (no release manifest -> version gate skipped).
//   capability_gap  a Randall feature request (wishes)
// Unknown kinds are filed as bugs rather than refused.
//
// Reports are accepted anonymously. If the client sends its Discord-linked
// Supabase token we resolve the Discord username for the embed; an invalid
// token degrades to anonymous rather than failing — nobody opted into auth to
// file a bug. Outdated clients are refused with 426 so "update first" is
// always step one. Retention is R2 lifecycle rules, not code (see README).

const SERVICE = "nucleus-bugreport";
const VERSION = 1;

const ID_RE = /^[0-9a-f]{32}$/;
// X.Y.Z, optionally with a prerelease tag (0.9.0-preview.7): secret-link test
// builds are stamped that way and must still be able to file reports.
const VER_RE = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,31})?$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY_RE = /^\d{8}$/;
const CHANNELS = new Set(["windows", "mac", "linux"]);
// A platform without a desktop release manifest; allowed for chat reports only.
const MOBILE_PLATFORM = "mobile";
const KINDS = new Set(["bug", "chat", "capability_gap"]);
const CHAT_SURFACES = new Set(["mods", "tracker", "mobile"]);
const KIND_LABEL = {
  bug: { title: "", username: "Nucleus bug reports", file: "bugreport", color: 0xd4a83b },
  chat: { title: "💬 Randall chat report", username: "Nucleus chat reports", file: "chatreport", color: 0x5b8def },
  capability_gap: { title: "💡 Randall feature request", username: "Nucleus bug reports", file: "wish", color: 0x7bc47f },
};

const DESCRIPTION_MAX = 4000;
const CONTACT_MAX = 200;
const EXTRA_JSON_MAX = 16 * 1024; // electron diagnostics blob, serialized
const RENDERER_ERRORS_MAX = 50;
const META_BODY_MAX = 96 * 1024; // raw POST body
const SLOT_TTL_MS = 60 * 60 * 1000; // an unfilled slot dies after an hour
const MANIFEST_TTL_MS = 5 * 60 * 1000;
const DISCORD_ATTACH_MAX = 8 * 1024 * 1024; // attach the zip itself under this
const DISCORD_DESC_MAX = 1500;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
  });

// The mobile vault (a different origin) sends JSON and a zip body, both of
// which need a preflight. Answering it exposes nothing new: every route
// already sends access-control-allow-origin: *.
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, PUT, OPTIONS",
  "access-control-allow-headers": "content-type, authorization",
  "access-control-max-age": "86400",
};
const preflight = () => new Response(null, { status: 204, headers: CORS });

const bearer = (req) => (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const newId = () => hex(crypto.getRandomValues(new Uint8Array(16)));
const dayStamp = (ms) => new Date(ms).toISOString().slice(0, 10).replace(/-/g, "");

const keyZip = (day, id) => `r/${day}/${id}/report.zip`;
const keyMeta = (day, id) => `r/${day}/${id}/meta.json`;
const keySlot = (id) => `s/${id}`;
const keyDone = (id) => `d/${id}`;

const intVar = (v, dflt) => {
  const n = parseInt(v, 10);
  return Number.isFinite(n) && n > 0 ? n : dflt;
};
const maxZipBytes = (env) => intVar(env.MAX_ZIP_BYTES, 64 * 1024 * 1024);
const retentionMs = (env) => intVar(env.RETENTION_DAYS, 90) * 24 * 60 * 60 * 1000;

// --- version gate ------------------------------------------------------------

// Same numeric-segment compare as electron/updates/updater.js so the worker and the
// app agree on what "older" means.
// A prerelease tag counts as older than the same X.Y.Z release (semver): a
// 0.9.0-preview build is outdated once 0.9.0 ships, and newer than 0.8.9.
export function compareVersions(a, b) {
  const [ca, ta] = String(a).split("-", 2);
  const [cb, tb] = String(b).split("-", 2);
  const pa = ca.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = cb.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const da = pa[i] || 0;
    const db = pb[i] || 0;
    if (da !== db) return da > db ? 1 : -1;
  }
  if (!ta && tb) return 1;
  if (ta && !tb) return -1;
  return 0;
}

// {channel: {version, url, notes, at}} — module-level so warm isolates reuse
// it. release_to_r2.py writes latest.json with no-cache, so this 5-minute
// window is the only caching; a new release gates within minutes.
const manifestCache = new Map();

async function latestVersion(env, channel) {
  const hit = manifestCache.get(channel);
  if (hit && Date.now() - hit.at < MANIFEST_TTL_MS) return hit;
  try {
    const r = await fetch(`${env.RELEASES_BASE}/${channel}/latest.json`, {
      headers: { "cache-control": "no-cache" },
      cf: { cacheTtl: 300 },
    });
    if (!r.ok) return null;
    const m = await r.json();
    if (!m || !VER_RE.test(m.version || "")) return null;
    const platforms = m.platforms && typeof m.platforms === "object" ? m.platforms : {};
    const first = Object.values(platforms).find((p) => p && typeof p.url === "string");
    const entry = {
      version: m.version,
      url: first ? first.url : null,
      notes: typeof m.notes === "string" ? m.notes.slice(0, 500) : "",
      at: Date.now(),
    };
    manifestCache.set(channel, entry);
    return entry;
  } catch {
    return null; // fail OPEN — a manifest outage must not block bug reports
  }
}

// --- identity ------------------------------------------------------------------
// bugreport_identity() reads the names from the Discord sign-in record. It
// replaced friends_hub_identity() when Friends was taken down (0.8.16); the
// response shape is the same.

async function resolveIdentity(env, token) {
  if (typeof token !== "string" || token.length < 20 || token.length > 4096) return null;
  try {
    const r = await fetch(`${env.SUPABASE_URL}/rest/v1/rpc/bugreport_identity`, {
      method: "POST",
      headers: {
        apikey: env.SUPABASE_ANON_KEY,
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      body: "{}",
    });
    if (!r.ok) return null;
    const d = await r.json();
    if (!d || !UUID_RE.test(d.user_id || "")) return null;
    const p = d.profile && typeof d.profile === "object" ? d.profile : {};
    const str = (v, n) => (typeof v === "string" ? v.slice(0, n) : null);
    return {
      uid: d.user_id.toLowerCase(),
      discord_username: str(p.discord_username, 40),
      display_name: str(p.display_name, 40),
    };
  } catch {
    return null;
  }
}

// --- signed admin links ------------------------------------------------------

async function hmacHex(secret, msg) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return hex(new Uint8Array(sig));
}

const sigInput = (id, kind, day, exp) => `${id}.${kind}.${day}.${exp}`;

async function signedUrl(env, origin, id, kind, day, exp) {
  if (!env.LINK_SIGNING_SECRET) return null;
  const sig = await hmacHex(env.LINK_SIGNING_SECRET, sigInput(id, kind, day, exp));
  return `${origin}/bugreport/${id}/${kind}?d=${day}&exp=${exp}&sig=${sig}`;
}

async function verifySig(env, id, kind, day, exp, sig) {
  if (!env.LINK_SIGNING_SECRET || !DAY_RE.test(day || "") || !/^[0-9a-f]{64}$/.test(sig || "")) return false;
  const expN = Number(exp);
  if (!Number.isFinite(expN) || expN < Date.now()) return false;
  const want = await hmacHex(env.LINK_SIGNING_SECRET, sigInput(id, kind, day, String(expN)));
  // Constant-time compare: both are 64-char hex, so XOR char codes.
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= want.charCodeAt(i) ^ sig.charCodeAt(i);
  return diff === 0;
}

// --- validation --------------------------------------------------------------

const clipStr = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");
const count = (v) => (Number.isInteger(v) && v >= 0 && v < 1e6 ? v : null);

function cleanChat(raw) {
  const c = raw && typeof raw === "object" ? raw : {};
  return {
    surface: CHAT_SURFACES.has(c.surface) ? c.surface : "unknown",
    message_count: count(c.message_count),
    tool_calls: count(c.tool_calls),
    errors: count(c.errors),
    conversation_id: clipStr(c.conversation_id, 64),
    model: clipStr(c.model, 80),
  };
}

export function cleanMeta(body, env) {
  if (!body || typeof body !== "object") return { error: "bad json" };
  // Absent or unknown kind is a bug report: released clients never send one.
  const kind = KINDS.has(body.kind) ? body.kind : "bug";
  const platform = typeof body.platform === "string" ? body.platform : "";
  const mobileChat = kind === "chat" && platform === MOBILE_PLATFORM;
  if (!CHANNELS.has(platform) && !mobileChat) return { error: "bad platform", field: "platform" };
  const app_version = typeof body.app_version === "string" ? body.app_version.trim() : "";
  if (!VER_RE.test(app_version)) return { error: "bad version", field: "app_version" };
  let description = typeof body.description === "string" ? body.description.trim() : "";
  // A chat report's note is optional: the conversation IS the report.
  if (!description && kind === "chat") description = "(no note)";
  if (!description || description.length > DESCRIPTION_MAX) return { error: "bad description", field: "description" };
  const contact = typeof body.contact === "string" ? body.contact.trim().slice(0, CONTACT_MAX) : "";
  const zip_size = body.zip_size;
  if (!Number.isInteger(zip_size) || zip_size <= 0 || zip_size > maxZipBytes(env)) {
    return { error: "bad zip_size", field: "zip_size", max: maxZipBytes(env) };
  }
  let electron = null;
  if (body.electron && typeof body.electron === "object") {
    const s = JSON.stringify(body.electron);
    electron = s.length <= EXTRA_JSON_MAX ? body.electron : { truncated: true };
  }
  const renderer_errors = Array.isArray(body.renderer_errors)
    ? body.renderer_errors.slice(0, RENDERER_ERRORS_MAX).map((e) => ({
        ts: typeof e?.ts === "string" ? e.ts.slice(0, 40) : null,
        message: typeof e?.message === "string" ? e.message.slice(0, 1000) : "",
        stack: typeof e?.stack === "string" ? e.stack.slice(0, 4000) : null,
      }))
    : [];
  const truncated = body.truncated === true;
  const meta = { kind, platform, app_version, description, contact, zip_size, electron, renderer_errors, truncated };
  if (kind === "chat") meta.chat = cleanChat(body.chat);
  return { meta };
}

// --- Discord -----------------------------------------------------------------

const labelFor = (meta) => KIND_LABEL[meta.kind] || KIND_LABEL.bug;

export function buildEmbed(meta, downloadUrl) {
  const label = labelFor(meta);
  const who = meta.reporter?.discord_username
    ? `@${meta.reporter.discord_username}`
    : meta.reporter?.display_name || "anonymous";
  const fields = [
    { name: "Reporter", value: who.slice(0, 1024), inline: true },
    { name: "Contact", value: (meta.contact || "—").slice(0, 1024), inline: true },
    { name: "Zip", value: `${(meta.size / (1024 * 1024)).toFixed(1)} MB${meta.truncated ? " (truncated)" : ""}`, inline: true },
    { name: "Version gate", value: meta.gate, inline: true },
  ];
  if (meta.kind === "chat" && meta.chat) {
    const c = meta.chat;
    const n = (v) => (v == null ? "?" : String(v));
    fields.push(
      { name: "Surface", value: c.surface, inline: true },
      { name: "Messages", value: n(c.message_count), inline: true },
      { name: "Tool calls", value: n(c.tool_calls), inline: true },
      { name: "Errors", value: n(c.errors), inline: true },
      { name: "Model", value: (c.model || "—").slice(0, 1024), inline: true },
    );
  } else {
    fields.push({ name: "Renderer errors", value: String((meta.renderer_errors || []).length), inline: true });
  }
  fields.push({ name: "Id", value: meta.id, inline: false });
  const head = `v${meta.app_version} · ${meta.platform}`;
  const embed = {
    title: (label.title ? `${label.title} · ${head}` : head).slice(0, 256),
    description: meta.description.slice(0, DISCORD_DESC_MAX)
      + (meta.description.length > DISCORD_DESC_MAX ? "\n…(full text in report.json)" : ""),
    fields,
    timestamp: new Date(meta.stored).toISOString(),
    color: label.color,
  };
  if (downloadUrl) embed.url = downloadUrl;
  return embed;
}

export async function notifyDiscord(env, meta, downloadUrl, zipObject) {
  if (!env.DISCORD_WEBHOOK_URL) return false;
  const payload = {
    username: labelFor(meta).username,
    embeds: [buildEmbed(meta, downloadUrl)],
  };
  try {
    let r;
    if (zipObject && meta.size <= DISCORD_ATTACH_MAX) {
      const form = new FormData();
      form.append("payload_json", JSON.stringify(payload));
      form.append("files[0]", await zipObject.blob(), `${labelFor(meta).file}-${meta.id.slice(0, 8)}.zip`);
      r = await fetch(`${env.DISCORD_WEBHOOK_URL}?wait=true`, { method: "POST", body: form });
    } else {
      r = await fetch(`${env.DISCORD_WEBHOOK_URL}?wait=true`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    return r.ok;
  } catch {
    return false;
  }
}

// --- handlers ----------------------------------------------------------------

async function handleCreate(req, env) {
  if (!env.REPORTS) return json({ error: "report store not configured" }, 503);
  const ip = req.headers.get("cf-connecting-ip") || "0.0.0.0";
  if (env.REPORT_LIMITER) {
    try {
      const { success } = await env.REPORT_LIMITER.limit({ key: ip });
      if (!success) return json({ error: "rate_limited", retry_after: 60 }, 429);
    } catch {
      // a broken limiter must not block reports
    }
  }
  const raw = await req.text();
  if (raw.length > META_BODY_MAX) return json({ error: "too large" }, 413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const cleaned = cleanMeta(body, env);
  if (cleaned.error) return json(cleaned, 400);
  const meta = cleaned.meta;

  // The mobile vault has no release manifest; its chat reports skip the gate.
  const mobile = meta.platform === MOBILE_PLATFORM;
  const latest = mobile ? null : await latestVersion(env, meta.platform);
  if (latest && compareVersions(meta.app_version, latest.version) < 0) {
    return json({
      error: "outdated",
      current: meta.app_version,
      latest: latest.version,
      url: latest.url,
      notes: latest.notes,
    }, 426);
  }
  meta.gate = mobile ? "n/a (mobile)" : latest ? `ok (latest ${latest.version})` : "unchecked";

  const token = bearer(req);
  meta.reporter = token ? await resolveIdentity(env, token) : null;

  const now = Date.now();
  const id = newId();
  const ipHash = hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip)))).slice(0, 16);
  const slot = { ...meta, id, day: dayStamp(now), created: now, ip_hash: ipHash };
  await env.REPORTS.put(keySlot(id), JSON.stringify(slot), {
    httpMetadata: { contentType: "application/json" },
  });
  return json({ id, max_zip_bytes: maxZipBytes(env), upload_ttl_s: SLOT_TTL_MS / 1000 });
}

async function handleUpload(req, env, id) {
  if (!env.REPORTS) return json({ error: "report store not configured" }, 503);
  // Checked before the slot: this id is already stored, and only its reply
  // was lost. Answer from the receipt; never store or ping twice.
  const doneObj = await env.REPORTS.get(keyDone(id));
  if (doneObj) {
    const done = await doneObj.json();
    return json({ ok: true, id, notified: !!done.notified, already_stored: true });
  }
  const slotObj = await env.REPORTS.get(keySlot(id));
  if (!slotObj) return json({ error: "unknown report" }, 404);
  const slot = await slotObj.json();
  if (Date.now() - slot.created > SLOT_TTL_MS) {
    await env.REPORTS.delete(keySlot(id));
    return json({ error: "slot expired" }, 410);
  }
  const declared = Number(req.headers.get("content-length"));
  if (!Number.isFinite(declared) || declared <= 0) return json({ error: "content-length required" }, 411);
  if (declared > maxZipBytes(env)) return json({ error: "too large", max: maxZipBytes(env) }, 413);
  if (declared !== slot.zip_size) return json({ error: "size mismatch", expected: slot.zip_size, got: declared }, 400);

  const zipKey = keyZip(slot.day, id);
  // Stream — never buffer the body; the isolate has 128 MB and the zip may be 64.
  await env.REPORTS.put(zipKey, req.body, {
    httpMetadata: { contentType: "application/zip" },
    customMetadata: { id, app_version: slot.app_version, platform: slot.platform, kind: slot.kind || "bug" },
  });
  // Cheap sanity check: a zip starts with "PK".
  const head = await env.REPORTS.get(zipKey, { range: { offset: 0, length: 2 } });
  const magic = head ? new Uint8Array(await head.arrayBuffer()) : null;
  if (!magic || magic.length < 2 || magic[0] !== 0x50 || magic[1] !== 0x4b) {
    await env.REPORTS.delete(zipKey);
    return json({ error: "not a zip" }, 400);
  }

  const now = Date.now();
  const expires = now + retentionMs(env);
  const origin = new URL(req.url).origin;
  const download = await signedUrl(env, origin, id, "zip", slot.day, expires);
  const metaUrl = await signedUrl(env, origin, id, "meta", slot.day, expires);
  const meta = { ...slot, size: declared, stored: now, expires, download, meta_url: metaUrl, notified: false };

  const zipObject = declared <= DISCORD_ATTACH_MAX ? await env.REPORTS.get(zipKey) : null;
  meta.notified = await notifyDiscord(env, meta, download, zipObject);

  await env.REPORTS.put(keyMeta(slot.day, id), JSON.stringify(meta), {
    httpMetadata: { contentType: "application/json" },
  });
  // The receipt is written before the slot goes, so there is no moment where
  // a stored report answers 404.
  await env.REPORTS.put(keyDone(id), JSON.stringify({ id, day: slot.day, stored: now, notified: meta.notified }), {
    httpMetadata: { contentType: "application/json" },
  });
  await env.REPORTS.delete(keySlot(id));
  return json({ ok: true, id, notified: meta.notified });
}

async function handleDownload(req, env, id, kind) {
  if (!env.REPORTS) return json({ error: "report store not configured" }, 503);
  const u = new URL(req.url);
  const day = u.searchParams.get("d");
  const ok = await verifySig(env, id, kind, day, u.searchParams.get("exp"), u.searchParams.get("sig"));
  if (!ok) return json({ error: "forbidden" }, 403);
  const key = kind === "zip" ? keyZip(day, id) : keyMeta(day, id);
  const obj = await env.REPORTS.get(key);
  if (!obj) return json({ error: "gone" }, 404);
  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("etag", obj.httpEtag);
  headers.set("cache-control", "private, no-store");
  if (kind === "zip") {
    headers.set("content-disposition", `attachment; filename="${(KIND_LABEL[obj.customMetadata?.kind] || KIND_LABEL.bug).file}-${id.slice(0, 8)}.zip"`);
  }
  return new Response(obj.body, { headers });
}

// --- admin: list + fetch reports -------------------------------------------
// The developer reads reports with tools/admin/bug_reports.py. The R2 API
// token on the dev machine is scoped to the releases bucket, so reading goes
// through this worker, which already holds the REPORTS binding. Bearer
// ADMIN_TOKEN (wrangler secret); unset -> the admin routes do not exist.

async function adminAuthorized(req, env) {
  const want = env.ADMIN_TOKEN || "";
  const got = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!want || want.length < 32 || !got) return false;
  // Compare HMACs of both values, so the comparison never leaks via timing.
  const a = await hmacHex(want, want), b = await hmacHex(want, got);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function utcDay(msAgo) {
  const d = new Date(Date.now() - msAgo);
  return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}`;
}

export async function handleAdmin(req, env, parts, url) {
  if (!env.ADMIN_TOKEN) return json({ error: "not found" }, 404);
  if (!(await adminAuthorized(req, env))) return json({ error: "unauthorized" }, 401);
  if (req.method !== "GET") return json({ error: "method not allowed" }, 405);
  // /bugreport/admin/list?days=N&kind=chat
  if (parts[2] === "list") {
    const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "7", 10) || 7, 1), 90);
    const kind = url.searchParams.get("kind") || "";
    const reports = [];
    for (let i = 0; i < days; i++) {
      const day = utcDay(i * 86400000);
      let cursor;
      do {
        const page = await env.REPORTS.list({ prefix: `r/${day}/`, cursor, include: ["customMetadata"] });
        for (const obj of page.objects) {
          if (!obj.key.endsWith("/meta.json")) continue;
          const id = obj.key.split("/")[2];
          const m = obj.customMetadata || {};
          if (kind && (m.kind || "bug") !== kind) continue;
          reports.push({ day, id, uploaded: obj.uploaded, size: obj.size, kind: m.kind || "bug",
                         platform: m.platform || "", app_version: m.app_version || "" });
        }
        cursor = page.truncated ? page.cursor : undefined;
      } while (cursor);
    }
    reports.sort((x, y) => String(y.uploaded).localeCompare(String(x.uploaded)));
    return json({ reports });
  }
  // /bugreport/admin/<day>/<id>/(meta|zip)
  const [, , day, id, what] = parts;
  if (!DAY_RE.test(day || "") || !ID_RE.test(id || "") || !["meta", "zip"].includes(what)) return json({ error: "not found" }, 404);
  const obj = await env.REPORTS.get(what === "zip" ? keyZip(day, id) : keyMeta(day, id));
  if (!obj) return json({ error: "gone" }, 404);
  const headers = new Headers({ "cache-control": "private, no-store" });
  obj.writeHttpMetadata(headers);
  return new Response(obj.body, { headers });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
    // parts: ["bugreport", id?, kind?]
    if (parts[0] !== "bugreport") return json({ error: "not found" }, 404);
    if (req.method === "OPTIONS") return preflight();
    if (parts[1] === "admin") return handleAdmin(req, env, parts, url);

    if (parts.length === 1) {
      if (req.method === "POST") return handleCreate(req, env);
      if (req.method === "GET") return json({ service: SERVICE, version: VERSION });
      return json({ error: "method not allowed" }, 405);
    }
    const id = parts[1];
    if (!ID_RE.test(id)) return json({ error: "bad id" }, 400);
    const kind = parts[2];
    if (kind === "zip" && req.method === "PUT") return handleUpload(req, env, id);
    if ((kind === "zip" || kind === "meta") && req.method === "GET") return handleDownload(req, env, id, kind);
    return json({ error: "not found" }, 404);
  },
};
