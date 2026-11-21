const crypto = require('node:crypto');

function windowHandle(sourceId) {
  const match = /^window:(\d+):[01]$/.exec(sourceId || '');
  return match ? BigInt(match[1]).toString() : null;
}

// Where the game sits inside the captured window frame (the frame includes
// Dolphin's title bar and borders). Presentation only: the renderer crops the
// title bar out with it. Anything malformed becomes null (show the whole frame).
function clientGeometry(value) {
  if (!value || typeof value !== 'object') return null;
  const keys = ['x', 'y', 'width', 'height', 'frameWidth', 'frameHeight'];
  if (!keys.every(key => Number.isSafeInteger(value[key]) && value[key] >= 0 && value[key] <= 32768)) return null;
  const { x, y, width, height, frameWidth, frameHeight } = value;
  if (!width || !height || x + width > frameWidth || y + height > frameHeight) return null;
  return { x, y, width, height, frameWidth, frameHeight };
}

function sameTarget(a, b) {
  return !!a && !!b && a.found === true && b.found === true &&
    typeof a.sessionId === 'string' && a.sessionId === b.sessionId &&
    a.pid === b.pid && String(a.hwnd) === String(b.hwnd);
}

// Source identity comes only from the authenticated backend's retained
// DolphinBoot process. Renderer arguments never choose a PID/HWND/source.
function createDolphinCaptureHost({ desktopCapturer, readTarget, presentTarget,
  isTrusted, platform = process.platform, now = Date.now }) {
  let current = null;
  let generation = 0;
  let presentation = Promise.resolve();
  const serialize = action => {
    const result = presentation.then(action);
    presentation = result.catch(() => {});
    return result;
  };
  const trusted = event => {
    if (!isTrusted(event)) throw new Error('Untrusted Dolphin capture request');
  };
  const owns = (event, leaseId) => current && current.leaseId === leaseId &&
    current.owner === event.sender && current.frame === event.senderFrame;
  return {
    async prepare(event, expectedSessionId) {
      trusted(event);
      if (platform !== 'win32') return { supported: false, found: false };
      if (expectedSessionId !== undefined && (typeof expectedSessionId !== 'string' || expectedSessionId.length > 160))
        throw new Error('Invalid expected Dolphin session');
      // A stale chat card cannot revoke another panel's lease during prepare.
      if (expectedSessionId && (await readTarget())?.sessionId !== expectedSessionId)
        return { supported: true, found: false };
      const revision = ++generation;
      current = null;
      const target = await readTarget();
      if (revision !== generation) return { supported: true, found: false };
      if (!target?.found) return { supported: target?.supported !== false, found: false };
      if (expectedSessionId && target.sessionId !== expectedSessionId) return { supported: true, found: false };
      if (!/^[1-9]\d*$/.test(String(target.hwnd)) || typeof target.sessionId !== 'string' || !Number.isSafeInteger(target.pid))
        throw new Error('Invalid owned Dolphin capture target');
      const sources = await desktopCapturer.getSources({ types: ['window'],
        thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false });
      const source = sources.find(value => windowHandle(value.id) === String(target.hwnd));
      if (!source || revision !== generation || !sameTarget(target, await readTarget()))
        return { supported: true, found: false };
      if (!isTrusted(event) || revision !== generation) return { supported: true, found: false };
      current = { target, leaseId: crypto.randomUUID(), owner: event.sender,
        frame: event.senderFrame, expires: now() + 15000, confirmed: false };
      return { supported: true, found: true, leaseId: current.leaseId, sourceId: source.id, sessionId: target.sessionId,
        client: clientGeometry(target.client) };
    },
    check(event, leaseId, { present = false, separate = false } = {}) {
      return serialize(async () => {
        trusted(event);
        if (!owns(event, leaseId)) return { active: false };
        const lease = current;
        let target;
        try { target = await readTarget(); } catch (error) { lease.expires = 0; throw error; }
        if (current !== lease || !sameTarget(lease.target, target)) {
          if (current === lease) current = null;
          return { active: false };
        }
        if (present || separate) {
          lease.presentationRequested = true;
          const result = await presentTarget(lease.target, separate ? 'separate' : 'behind');
          if (!result?.found || current !== lease) return { active: false };
          lease.confirmed = true;
        }
        lease.expires = now() + 15000;
        return { active: true, client: clientGeometry(target.client) };
      });
    },
    separate(event, leaseId) {
      return serialize(async () => {
        trusted(event);
        const lease = current;
        if (leaseId && !owns(event, leaseId)) return { active: false };
        const revision = generation;
        const target = await readTarget();
        if (!target?.found || !isTrusted(event) || revision !== generation ||
            (leaseId && !sameTarget(lease.target, target))) return { active: false };
        const result = await presentTarget(target, 'separate');
        if (revision === generation) { current = null; generation++; }
        return { active: !!result?.found };
      });
    },
    release(event, leaseId) {
      trusted(event);
      if (owns(event, leaseId)) { current = null; generation++; }
    },
    revoke() {
      const lease = current;
      current = null; generation++;
      // Navigation/crash cannot ask the old frame to clean up its native window.
      if (lease?.presentationRequested) serialize(async () => {
        const target = await readTarget();
        if (sameTarget(lease.target, target)) return presentTarget(lease.target, 'separate');
      }).catch(() => {});
    },
    allowsMedia(webContents, details = {}) {
      return !!current && current.owner === webContents && current.expires >= now() &&
        current.frame === webContents.mainFrame && details.isMainFrame === true &&
        (!details.requestingUrl || details.requestingUrl === current.frame.url) &&
        (!details.mediaTypes || details.mediaTypes.every(type => type === 'video')) &&
        (!details.mediaType || details.mediaType === 'video');
    }
  };
}

function installCapturePermissions(session, host) {
  // Preserve Electron's previous non-media permission behavior.
  session.setPermissionCheckHandler((contents, permission, _origin, details) =>
    permission !== 'media' || host.allowsMedia(contents, details));
  session.setPermissionRequestHandler((contents, permission, callback, details) =>
    callback(permission !== 'media' || host.allowsMedia(contents, details)));
}
module.exports = { createDolphinCaptureHost, installCapturePermissions, windowHandle, sameTarget, clientGeometry };
