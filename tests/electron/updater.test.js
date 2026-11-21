const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');

test('update manifests reject tampering and untrusted download origins', async () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-updater-'));
  const publicKeyPath = path.join(tempDir, 'public.pem');
  const originalLoad = Module._load;
  const originalPublicKeyPath = process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH;
  const updaterPath = require.resolve('../../app/electron/updates/updater');

  try {
    const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
    fs.writeFileSync(publicKeyPath, publicKey.export({ type: 'spki', format: 'pem' }));
    process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH = publicKeyPath;
    Module._load = function load(request, parent, isMain) {
      if (request === 'electron') return { app: { isPackaged: false } };
      return originalLoad.call(this, request, parent, isMain);
    };
    delete require.cache[updaterPath];

    const {
      canonicalJson,
      verifyManifestSignature,
      allowedNetworkUrl,
      trackCompletedUpdate,
    } = require('../../app/electron/updates/updater')._test;
    const manifest = {
      version: '1.2.3',
      windows: {
        url: 'https://releases.ssbmnucleus.net/test.exe',
        sha256: 'a'.repeat(64),
        size: 1,
      },
    };
    manifest.signature = {
      algorithm: 'ed25519',
      value: crypto.sign(
        null,
        Buffer.from(canonicalJson(manifest)),
        privateKey
      ).toString('base64'),
    };

    assert.doesNotThrow(() => verifyManifestSignature(manifest));
    manifest.version = '1.2.4';
    assert.throws(() => verifyManifestSignature(manifest), /signature/i);
    assert.equal(
      allowedNetworkUrl('https://releases.ssbmnucleus.net/windows/update.exe').href,
      'https://releases.ssbmnucleus.net/windows/update.exe'
    );
    assert.throws(() => allowedNetworkUrl('https://example.com/update.exe'), /trusted/);
    assert.throws(
      () => allowedNetworkUrl('http://releases.ssbmnucleus.net/windows/update.exe'),
      /trusted/
    );

    let requestOptions;
    let requestBody;
    const requestImpl = (options, onResponse) => {
      requestOptions = options;
      const req = new (require('node:events').EventEmitter)();
      req.setTimeout = () => {};
      req.destroy = () => {};
      req.end = (body) => {
        requestBody = JSON.parse(body.toString('utf8'));
        const res = new (require('node:events').EventEmitter)();
        res.resume = () => {};
        onResponse(res);
        process.nextTick(() => res.emit('end'));
      };
      return req;
    };
    await trackCompletedUpdate('1.2.3', requestImpl);
    assert.equal(requestOptions.hostname, 'nttxcjrnqccogsibeqzz.supabase.co');
    assert.equal(requestOptions.path, '/rest/v1/rpc/api_track_app_update');
    assert.equal(requestOptions.method, 'POST');
    assert.deepEqual(requestBody, {
      p_version: '1.2.3',
      p_platform: process.platform === 'win32'
        ? 'windows-x86_64'
        : process.platform === 'darwin' ? 'mac-arm64' : 'linux-x86_64',
    });
  } finally {
    Module._load = originalLoad;
    delete require.cache[updaterPath];
    if (originalPublicKeyPath === undefined) {
      delete process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH;
    } else {
      process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH = originalPublicKeyPath;
    }
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
