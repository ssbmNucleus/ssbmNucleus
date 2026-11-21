'use strict';

const { randomUUID } = require('node:crypto');

// One frame in Electron IPC and one replacement waiting locally. A slow or
// suspended renderer cannot accumulate an unbounded queue of JPEG buffers.
class ViewerFrameRelay {
  constructor(deliver) { this.deliver = deliver; this.sequence = 0; this.reset(null); }
  reset(viewerSessionId) {
    this.viewerSessionId = viewerSessionId;
    this.inFlight = null;
    this.pending = null;
  }
  push(buffer) {
    if (!this.viewerSessionId) return;
    if (this.inFlight) { this.pending = buffer; return; }
    const metadata = { viewerSessionId: this.viewerSessionId, frameId: ++this.sequence };
    this.inFlight = metadata;
    try {
      if (this.deliver(buffer, metadata) === false) this.inFlight = null;
    } catch { this.inFlight = null; }
  }
  consumed(metadata) {
    if (!this.inFlight || metadata?.viewerSessionId !== this.inFlight.viewerSessionId
        || metadata?.frameId !== this.inFlight.frameId) return false;
    this.inFlight = null;
    const next = this.pending;
    this.pending = null;
    if (next) this.push(next);
    return true;
  }
}

function viewerTransport(platform = process.platform, override = process.env.NUCLEUS_VIEWER_TRANSPORT) {
  if (override && !['stream', 'embedded'].includes(override)) throw new Error('Unknown viewer transport override.');
  if (override === 'embedded' && platform !== 'win32') throw new Error('The native window fallback is only available on Windows.');
  return override === 'embedded' ? 'embedded' : 'stream';
}

class ViewerSession {
  constructor({ createManager, onMessage, onFrame }) {
    this.createManager = createManager;
    this.onMessage = onMessage;
    this.frames = new ViewerFrameRelay(onFrame);
    this.manager = null;
    this.generation = 0;
  }
  async start(options) {
    const generation = ++this.generation;
    const previous = this.manager;
    this.manager = null;
    this.frames.reset(null);
    if (previous) await previous.stop();
    if (generation !== this.generation) throw new Error('Viewer start was superseded.');
    const manager = this.createManager(options);
    const viewerSessionId = options.viewerSessionId || randomUUID();
    this.manager = manager;
    this.frames.reset(viewerSessionId);
    const current = () => this.manager === manager && this.generation === generation;
    manager.onMessage('all', message => { if (current()) this.onMessage(message); });
    manager.onFrame = buffer => { if (current()) this.frames.push(buffer); };
    try {
      const result = await manager.start({ ...options, viewerSessionId });
      if (!current()) throw new Error('Viewer start was superseded.');
      return { ...result, viewerSessionId };
    } catch (error) {
      if (current()) { this.manager = null; this.frames.reset(null); }
      await manager.stop().catch(() => {});
      throw error;
    }
  }
  // Whether `viewerSessionId` is the app's running, connected viewer. A view kept while off screen asks this
  // when it comes back: another view's start replaces it without telling it (its messages are fenced off).
  running(viewerSessionId) {
    return Boolean(viewerSessionId) && this.manager?.viewerSessionId === viewerSessionId
      && this.manager.isConnected === true;
  }
  async stop(viewerSessionId) {
    if (viewerSessionId && viewerSessionId !== this.manager?.viewerSessionId) return false;
    ++this.generation;
    const manager = this.manager;
    this.manager = null;
    this.frames.reset(null);
    if (manager) await manager.stop();
    return true;
  }
}

module.exports = { ViewerFrameRelay, ViewerSession, viewerTransport };
