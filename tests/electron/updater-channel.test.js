const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const { Readable } = require('node:stream');
const { EventEmitter } = require('node:events');

const updaterPath = require.resolve('../../app/electron/updates/updater');
const PLATFORM_KEY = process.platform === 'win32' ? 'windows-x86_64'
  : process.platform === 'darwin' ? 'mac-arm64' : 'linux-x86_64';
const FOLDER = process.platform === 'win32' ? 'windows' : process.platform === 'darwin' ? 'mac' : 'linux';
const EXT = process.platform === 'win32' ? 'exe' : process.platform === 'darwin' ? 'dmg' : 'AppImage';
const HOST = 'https://releases.ssbmnucleus.net';
const STABLE_URL = `${HOST}/${FOLDER}/latest.json`;
// A made-up token for tests only; the real one lives with the release secrets.
const TOKEN = 'tEsT-channel_Token-0123';
const PREVIEW_URL = `${HOST}/${FOLDER}/preview/${TOKEN}/latest.json`;
const TEST_BUILD = { previewFeatures: 'assistant', previewChannel: TOKEN };

// Loads the real updater with electron, the packaged package.json, the pinned
// public key and the network stubbed. `routes` maps a URL (no query string) to
// { status, body } where body is an object (JSON) or a Buffer (artifact).
function loadUpdater({ isPackaged = true, version, packageJson = {}, routes }) {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  const requested = [];
  const responses = [];
  const keepAlives = new Set();
  const originalLoad = Module._load;
  const cached = require.cache[updaterPath];
  const app = {
    isPackaged,
    getVersion: () => version,
    getPath: () => os.tmpdir(),
  };
  const https = {
    get(url, optionsOrCallback, maybeCallback) {
      const callback = typeof optionsOrCallback === 'function' ? optionsOrCallback : maybeCallback;
      const key = `${url.origin}${url.pathname}`;
      requested.push(key);
      const req = new EventEmitter();
      req.setTimeout = () => {};
      req.destroyed = false;
      req.destroy = () => {
        req.destroyed = true;
        if (req.keepAlive) { clearInterval(req.keepAlive); keepAlives.delete(req.keepAlive); }
      };
      const route = routes[key] || { status: 404, body: Buffer.alloc(0) };
      // An error this request raises later (e.g. its own idle timeout firing
      // after the fetch has moved on to a redirect target).
      if (route.reqErrorAfterMs) {
        setTimeout(() => req.emit('error', new Error('Update check timed out')), route.reqErrorAfterMs);
      }
      const respond = () => {
        if (route.hang) {
          // A server that accepts and never answers. updater.js unrefs its
          // deadline timer, so the fake socket must hold the loop open itself
          // until the request is destroyed (or the test restores).
          req.keepAlive = setInterval(() => {}, 1000);
          keepAlives.add(req.keepAlive);
          return;
        }
        const body = route.body === undefined ? Buffer.alloc(0) : route.body;
        const payload = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
        let res;
        if (route.stall) {
          // Sends part of the body, then never finishes it.
          res = new Readable({ read() {} });
          res.push(payload.subarray(0, Math.max(1, payload.length >> 1)));
        } else {
          res = Readable.from([payload], { objectMode: false });
        }
        res.statusCode = route.status || 200;
        res.headers = { 'content-length': String(payload.length), ...(route.headers || {}) };
        responses.push({ key, req, res });
        callback(res);
      };
      if (route.delayMs) setTimeout(respond, route.delayMs);
      else queueMicrotask(respond);
      return req;
    },
  };
  Module._load = function load(request, parent, isMain) {
    if (request === 'electron') return { app };
    if (parent?.filename === updaterPath) {
      if (request === '../../package.json') return packageJson;
      if (request === 'https') return https;
      if (request === 'fs') {
        return { ...fs, readFileSync: () => publicKey.export({ type: 'spki', format: 'pem' }) };
      }
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  delete require.cache[updaterPath];
  const updater = require('../../app/electron/updates/updater');
  // Restore the loader immediately: updater.js resolves everything it needs at
  // load time except '../../package.json', which it re-reads per check. Keep a
  // narrow hook for that one request.
  Module._load = function load(request, parent, isMain) {
    if (request === '../../package.json' && parent?.filename === updaterPath) return packageJson;
    return originalLoad.call(this, request, parent, isMain);
  };
  const restore = () => {
    for (const timer of keepAlives) clearInterval(timer);
    keepAlives.clear();
    Module._load = originalLoad;
    if (cached) require.cache[updaterPath] = cached;
    else delete require.cache[updaterPath];
  };

  function signed(manifestVersion, artifact = {}) {
    const data = {
      version: manifestVersion,
      notes: `notes for ${manifestVersion}`,
      pub_date: '2026-09-25T00:00:00+00:00',
      platforms: { [PLATFORM_KEY]: {
        url: artifact.url || `${HOST}/${FOLDER}/SSBM-Nucleus_${manifestVersion}.${EXT}`,
        sha256: artifact.sha256 || 'a'.repeat(64),
        size: artifact.size || 1,
      } },
    };
    return { ...data, signature: { algorithm: 'ed25519', value: crypto.sign(
      null, Buffer.from(updater._test.canonicalJson(data)), privateKey).toString('base64') } };
  }

  return { updater, requested, responses, signed, restore };
}

test('channel selection: only a test build with a valid previewChannel token polls its secret manifest', () => {
  const { updater, restore } = loadUpdater({ version: '0.8.9', routes: {} });
  try {
    const { resolveUpdateSources } = updater._test;
    const channels = (options) => resolveUpdateSources({ platformFolder: 'windows', ...options })
      .map(({ channel, url, allowPrerelease }) => [channel, url, allowPrerelease]);
    const stable = ['stable', 'https://releases.ssbmnucleus.net/windows/latest.json', false];
    const preview = ['preview',
      `https://releases.ssbmnucleus.net/windows/preview/${TOKEN}/latest.json`, true];

    // A normal release build: public manifest only.
    assert.deepEqual(channels({ isPackaged: true, version: '0.8.9', packageJson: {} }), [stable]);
    assert.deepEqual(channels({ isPackaged: true, version: '0.8.9',
      packageJson: { previewFeatures: '', previewChannel: TOKEN } }), [stable],
    'a token alone does not make a release build a test build');

    // A test build with a prerelease version and a token (previewFeatures string/array/absent).
    assert.deepEqual(channels({ isPackaged: true, version: '0.9.0-preview.8',
      packageJson: { previewFeatures: 'assistant', previewChannel: TOKEN } }), [stable, preview]);
    assert.deepEqual(channels({ isPackaged: true, version: '0.9.0-preview.8',
      packageJson: { previewFeatures: ['assistant'], previewChannel: TOKEN } }), [stable, preview]);
    assert.deepEqual(channels({ isPackaged: true, version: '0.9.0-preview.8',
      packageJson: { previewChannel: TOKEN } }), [stable, preview]);

    // A "preview" packaged as plain 0.9.0 could never move on to stable 0.9.0
    // (not newer than itself), so its token is ignored: public manifest only.
    for (const features of ['assistant', ['assistant']]) {
      assert.deepEqual(channels({ isPackaged: true, version: '0.9.0',
        packageJson: { previewFeatures: features, previewChannel: TOKEN } }), [stable]);
    }

    // A test build without a token checks the public manifest only.
    assert.deepEqual(channels({ isPackaged: true, version: '0.9.0-preview.8',
      packageJson: { previewFeatures: 'assistant' } }), [stable]);
    // A malformed token is ignored, never spliced into a URL.
    for (const bad of ['short', 'x'.repeat(65), '../../windows/latest.json', 'has space in it 12345',
      '1234567890123456', 'token/with/slashes', 12345678901234567890, ['abcdefghijklmnopq'], null,
      `${TOKEN}
`, `
${TOKEN}`, `${TOKEN} `]) {
      assert.deepEqual(channels({ isPackaged: true, version: '0.9.0-preview.8',
        packageJson: { previewFeatures: 'assistant', previewChannel: bad } }), [stable], String(bad));
    }
    for (const good of ['a'.repeat(16), 'Z'.repeat(64), 'abc_DEF-123456789']) {
      assert.equal(channels({ isPackaged: true, version: '0.9.0-preview.8',
        packageJson: { previewChannel: good } }).length, 2, good);
    }

    // Dev override: unpackaged only, and it replaces every channel.
    const env = { NUCLEUS_UPDATE_MANIFEST_URL: 'http://127.0.0.1:9999/latest.json' };
    assert.deepEqual(channels({ isPackaged: false, env, version: '0.9.0-preview.8' }),
      [['override', env.NUCLEUS_UPDATE_MANIFEST_URL, true]]);
    assert.deepEqual(channels({ isPackaged: true, env, version: '0.8.9' }), [stable]);
    assert.deepEqual(channels({ isPackaged: true, env, version: '0.9.0-preview.8',
      packageJson: TEST_BUILD }), [stable, preview]);
  } finally {
    restore();
  }
});

test('the updater source names no preview manifest: only a packaged token can locate it', () => {
  const source = fs.readFileSync(updaterPath, 'utf8');
  assert.doesNotMatch(source, /preview\/latest\.json/);
  assert.match(source, /preview\/\$\{token\}\/latest\.json/);
});

test('a test build without a token never requests a preview manifest', async () => {
  const routes = {};
  const { updater, requested, signed, restore } = loadUpdater({
    version: '0.9.0-preview.8', packageJson: { previewFeatures: 'assistant' }, routes,
  });
  try {
    routes[STABLE_URL] = { body: signed('0.8.9') };
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.9') };
    routes[`${HOST}/${FOLDER}/preview/latest.json`] = { body: signed('0.9.0-preview.9') };
    assert.equal(await updater.check(), null);
    assert.ok(requested.every((url) => url === STABLE_URL), requested.join(', '));
  } finally {
    restore();
  }
});

test('a stable build never reads the preview manifest and refuses a prerelease on the public one', async () => {
  const routes = {};
  const { updater, requested, signed, restore } = loadUpdater({ version: '0.8.9', routes });
  try {
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.9') };
    routes[STABLE_URL] = { body: signed('0.8.9') };
    assert.equal(await updater.check(), null);
    routes[STABLE_URL] = { body: signed('0.9.0') };
    const update = await updater.check();
    assert.equal(update.version, '0.9.0');
    assert.equal(update.channel, 'stable');
    assert.ok(requested.length >= 2);
    assert.ok(requested.every((url) => url === STABLE_URL), requested.join(', '));

    // A prerelease published to the public manifest by mistake never reaches a stable install.
    routes[STABLE_URL] = { body: signed('0.9.1-preview.1') };
    await assert.rejects(updater.check(), /missing required signed fields/);
  } finally {
    restore();
  }
});

test('a preview build takes newer previews, numeric tag order, and moves to a newer stable', async () => {
  const routes = {};
  const { updater, requested, signed, restore } = loadUpdater({
    version: '0.9.0-preview.9', packageJson: TEST_BUILD, routes,
  });
  try {
    routes[STABLE_URL] = { body: signed('0.8.9') };
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.10') };
    let update = await updater.check();
    assert.equal(update.version, '0.9.0-preview.10', 'preview.10 is newer than preview.9');
    assert.equal(update.channel, 'preview');
    assert.ok(requested.includes(STABLE_URL) && requested.includes(PREVIEW_URL));

    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.9') };
    assert.equal(await updater.check(), null, 'the same preview is not an update');
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.8') };
    assert.equal(await updater.check(), null, 'an older preview is not an update');

    // 0.9.0 ships: the stable release outranks every 0.9.0 preview.
    routes[STABLE_URL] = { body: signed('0.9.0') };
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.12') };
    update = await updater.check();
    assert.equal(update.version, '0.9.0');
    assert.equal(update.channel, 'stable');

    // Same version in both channels installs as stable.
    routes[PREVIEW_URL] = { body: signed('0.9.0') };
    assert.equal((await updater.check()).channel, 'stable');

    // A later preview still wins over an older stable.
    routes[PREVIEW_URL] = { body: signed('0.9.1-preview.1') };
    assert.equal((await updater.check()).version, '0.9.1-preview.1');
  } finally {
    restore();
  }
});

test('one failing channel does not hide the other; all failing is a failed check', async () => {
  const routes = {};
  const { updater, signed, restore } = loadUpdater({
    version: '0.9.0-preview.8', packageJson: TEST_BUILD, routes,
  });
  const originalWarn = console.warn;
  console.warn = () => {};
  try {
    // Before the first preview publish the preview manifest is a 404.
    routes[STABLE_URL] = { body: signed('0.8.9') };
    assert.equal(await updater.check(), null);
    routes[STABLE_URL] = { body: signed('0.9.0') };
    assert.equal((await updater.check()).version, '0.9.0');

    // A tampered preview manifest is ignored, not installed.
    const tampered = signed('0.9.0-preview.9');
    tampered.version = '0.9.9';
    routes[PREVIEW_URL] = { body: tampered };
    routes[STABLE_URL] = { body: signed('0.8.9') };
    assert.equal(await updater.check(), null);

    delete routes[STABLE_URL];
    delete routes[PREVIEW_URL];
    await assert.rejects(updater.check(), /HTTP 404/);
  } finally {
    console.warn = originalWarn;
    restore();
  }
});

test('preview-to-preview update downloads from the prerelease folder and verifies the hash', async () => {
  const routes = {};
  const { updater, signed, restore } = loadUpdater({
    version: '0.9.0-preview.8', packageJson: TEST_BUILD, routes,
  });
  const originalLog = console.log;
  console.log = () => {};
  try {
    const installer = crypto.randomBytes(4096);
    const artifactUrl = `${HOST}/${FOLDER}/prerelease/tester-link/SSBM-Nucleus_0.9.0-preview.9_x64-setup.${EXT}`;
    routes[STABLE_URL] = { body: signed('0.8.9') };
    routes[PREVIEW_URL] = { body: signed('0.9.0-preview.9', {
      url: artifactUrl,
      sha256: crypto.createHash('sha256').update(installer).digest('hex'),
      size: installer.length,
    }) };
    routes[artifactUrl] = { body: installer };

    const update = await updater.check();
    assert.equal(update.url, artifactUrl);
    assert.doesNotThrow(() => updater._test.allowedNetworkUrl(update.url));

    const launched = [];
    const tracked = [];
    const overrides = {
      platform: 'win32',
      spawnDetachedWithRetry: async (file) => {
        launched.push(fs.readFileSync(file));
        fs.rmSync(path.dirname(file), { recursive: true, force: true });
      },
      trackCompletedUpdate: async (version) => { tracked.push(version); },
      schedule: () => {},
    };
    await updater.install(() => {}, overrides);
    assert.equal(launched.length, 1);
    assert.ok(launched[0].equals(installer), 'the launched installer is the verified download');
    assert.deepEqual(tracked, ['0.9.0-preview.9']);

    // Same size, different bytes: the signed SHA-256 refuses it.
    routes[artifactUrl] = { body: crypto.randomBytes(installer.length) };
    await updater.check();
    await assert.rejects(updater.install(() => {}, overrides), /checksum verification/);
    assert.equal(launched.length, 1);
  } finally {
    console.log = originalLog;
    restore();
  }
});

test('build.bat post-package gate: the token is baked as the exact string, and only with previewFeatures', () => {
  const { checkPackagedManifest } = require('../../tools/build/check_preview_channel');
  const packaged = { version: '0.9.0-preview.8', previewFeatures: 'assistant', previewChannel: TOKEN };
  assert.equal(checkPackagedManifest(packaged, TOKEN), null);
  assert.equal(checkPackagedManifest({ version: '0.9.0-preview.8', previewFeatures: 'assistant' }, ''), null);
  assert.match(checkPackagedManifest(packaged, ''), /NUCLEUS_PREVIEW_CHANNEL is not set/);
  assert.match(checkPackagedManifest({ ...packaged, previewChannel: 1234567890123456 }, '1234567890123456'),
    /got a number/);
  assert.match(checkPackagedManifest({ previewChannel: TOKEN }, TOKEN), /without previewFeatures/);
  assert.match(checkPackagedManifest({}, TOKEN), /got a undefined/);
  // A plain version could never move testers on to the matching stable release.
  assert.match(checkPackagedManifest({ ...packaged, version: '0.9.0' }, TOKEN),
    /without a prerelease tag/);
});

test('a preview manifest that redirects off-origin or hangs cannot cost the stable offer', async () => {
  const routes = {};
  const { updater, signed, restore } = loadUpdater({
    version: '0.9.0-preview.8', packageJson: TEST_BUILD, routes,
  });
  const originalWarn = console.warn;
  const warnings = [];
  console.warn = (message) => warnings.push(message);
  const originalLog = console.log;
  console.log = () => {};
  try {
    routes[STABLE_URL] = { body: signed('0.9.0') };

    // 302 to an untrusted host: the preview fetch rejects, stable still wins.
    routes[PREVIEW_URL] = { status: 302, headers: { location: 'https://evil.example/latest.json' } };
    const update = await updater.check();
    assert.equal(update.version, '0.9.0');
    assert.equal(update.channel, 'stable');
    assert.ok(warnings.some((w) => /preview manifest ignored: .*trusted releases origin/.test(w)),
      warnings.join('\n'));

    // A malformed Location rejects the same way.
    routes[PREVIEW_URL] = { status: 302, headers: { location: 'http://[bad' } };
    assert.equal((await updater.check()).version, '0.9.0');

    // An on-origin redirect is still followed.
    const moved = `${HOST}/${FOLDER}/preview/${TOKEN}/moved.json`;
    routes[PREVIEW_URL] = { status: 302, headers: { location: moved } };
    routes[moved] = { body: signed('0.9.1-preview.1') };
    assert.equal((await updater.check()).version, '0.9.1-preview.1');

    // A preview endpoint that never answers times out instead of hanging the check.
    updater._test.setManifestTimeoutForTest(50);
    routes[PREVIEW_URL] = { hang: true };
    const started = Date.now();
    assert.equal((await updater.check()).version, '0.9.0');
    assert.ok(Date.now() - started < 5000);
    assert.ok(warnings.some((w) => /preview manifest ignored: Update check timed out/.test(w)));

    // Both channels hanging is a failed check, not a pending one.
    routes[STABLE_URL] = { hang: true };
    await assert.rejects(updater.check(), /timed out/);
  } finally {
    updater._test.setManifestTimeoutForTest(null);
    console.warn = originalWarn;
    console.log = originalLog;
    restore();
  }
});

test('an installer download redirected off-origin rejects instead of hanging', async () => {
  const routes = {};
  const { updater, restore } = loadUpdater({ version: '0.9.0-preview.8', packageJson: TEST_BUILD, routes });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-redirect-'));
  try {
    const artifactUrl = `${HOST}/${FOLDER}/prerelease/x/SSBM-Nucleus_0.9.0-preview.9_x64-setup.${EXT}`;
    routes[artifactUrl] = { status: 302, headers: { location: 'https://evil.example/setup.exe' } };
    await assert.rejects(
      updater._test.downloadFile(artifactUrl, path.join(dir, 'update.bin'), 10),
      /trusted releases origin/,
    );
    routes[artifactUrl] = { status: 302, headers: { location: 'http://[bad' } };
    await assert.rejects(
      updater._test.downloadFile(artifactUrl, path.join(dir, 'update2.bin'), 10),
      /Invalid URL/,
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
    restore();
  }
});

test('a redirect retires the previous hop: its stalled body and late error cannot fail the new one', async () => {
  const routes = {};
  const { updater, responses, signed, restore } = loadUpdater({ version: '0.8.9', routes });
  const originalLog = console.log;
  console.log = () => {};
  try {
    // Astra's repro, scaled down: the first hop answers 302 with a body that
    // stalls, and later raises its own timeout error; the redirect target is
    // healthy but slower than that error.
    const moved = `${HOST}/${FOLDER}/moved/latest.json`;
    routes[STABLE_URL] = {
      status: 302, headers: { location: moved }, body: Buffer.from('partial redirect body'),
      stall: true, reqErrorAfterMs: 40,
    };
    routes[moved] = { body: signed('0.9.0'), delayMs: 120 };
    updater._test.setManifestTimeoutForTest(5000);
    const update = await updater.check();
    assert.equal(update.version, '0.9.0');

    const first = responses.find((r) => r.key === STABLE_URL);
    assert.ok(first.res.destroyed, 'the redirect response was destroyed');
    assert.ok(first.req.destroyed, 'the redirect request was destroyed');
    const second = responses.find((r) => r.key === moved);
    assert.equal(second.req.destroyed, false, 'the live hop was never destroyed');

    // The single overall deadline still bounds the whole redirect chain.
    updater._test.setManifestTimeoutForTest(60);
    routes[moved] = { hang: true };
    await assert.rejects(updater.check(), /Update check timed out/);
  } finally {
    updater._test.setManifestTimeoutForTest(null);
    console.log = originalLog;
    restore();
  }
});
