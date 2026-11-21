const crypto = require('crypto');

const CHANNELS = {
  import: 'nucleus-import',
  'patreon-link': 'nucleus-patreon',
};

function parseNucleusUrl(rawUrl, { allowLocalHttp = false } = {}) {
  let parsed;
  try { parsed = new URL(rawUrl); } catch { return null; }
  if (parsed.protocol !== 'nucleus:' || parsed.username || parsed.password || parsed.hash) return null;
  const action = parsed.hostname;
  if (!CHANNELS[action]) return null;

  let payload;
  if (action === 'import') {
    const download = parsed.searchParams.get('url');
    let source;
    try { source = new URL(download); } catch { return null; }
    const local = allowLocalHttp && source.protocol === 'http:'
      && ['localhost', '127.0.0.1'].includes(source.hostname);
    if (source.protocol !== 'https:' && !local) return null;
    payload = {
      url: source.toString(),
      name: parsed.searchParams.get('name'),
      title: parsed.searchParams.get('title'),
      type: parsed.searchParams.get('type'),
      effectType: parsed.searchParams.get('effect_type'),
    };
  } else {
    const token = parsed.searchParams.get('token');
    if (!token) return null;
    payload = {
      token,
      active: parsed.searchParams.get('active') === '1',
      name: parsed.searchParams.get('name'),
      // The OAuth state the app sent, when the website echoes it back; the window
      // checks it against the links it started (frontend patreonLinkGuard.js).
      state: parsed.searchParams.get('state'),
    };
  }
  const fingerprint = crypto.createHash('sha256')
    .update(`${CHANNELS[action]}\0${JSON.stringify(payload)}`).digest('hex');
  return { channel: CHANNELS[action], payload, fingerprint };
}

class ProtocolHandoffQueue {
  constructor(send, { now = Date.now, dedupeMs = 1500 } = {}) {
    this.send = send;
    this.now = now;
    this.dedupeMs = dedupeMs;
    this.ready = false;
    this.nextId = 1;
    this.queue = [];
    this.inflight = null;
    this.recent = new Map();
  }

  enqueue(item) {
    const at = this.now();
    for (const [key, seenAt] of this.recent) {
      if (at - seenAt >= this.dedupeMs) this.recent.delete(key);
    }
    const prior = this.recent.get(item.fingerprint);
    if (prior != null && at - prior < this.dedupeMs) return false;
    this.recent.set(item.fingerprint, at);
    this.queue.push({ ...item, id: this.nextId++ });
    this.flush();
    return true;
  }

  rendererReady() { this.ready = true; this.flush(); }
  rendererGone() {
    this.ready = false;
    if (this.inflight) this.queue.unshift(this.inflight);
    this.inflight = null;
  }

  acknowledge(id) {
    if (!this.inflight || this.inflight.id !== id) return false;
    this.inflight = null;
    this.flush();
    return true;
  }

  flush() {
    if (!this.ready || this.inflight || !this.queue.length) return;
    this.inflight = this.queue.shift();
    this.send(this.inflight.channel, {
      id: this.inflight.id,
      data: this.inflight.payload,
    });
  }
}

module.exports = { parseNucleusUrl, ProtocolHandoffQueue };
