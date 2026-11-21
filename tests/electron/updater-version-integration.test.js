const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const Module = require('node:module');
const { EventEmitter } = require('node:events');

test('actual signed updater accepts matching stable over preview and rejects older stable', async () => {
  const originalLoad = Module._load;
  const updaterPath = require.resolve('../../app/electron/updates/updater');
  const cachedModule = require.cache[updaterPath];
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  let manifest;
  const fs = require('node:fs');
  const channel = process.platform === 'win32' ? 'windows-x86_64' : process.platform === 'darwin' ? 'mac-arm64' : 'linux-x86_64';
  const ext = process.platform === 'win32' ? 'exe' : process.platform === 'darwin' ? 'dmg' : 'AppImage';
  const app = { isPackaged: true, getVersion: () => '0.8.2-preview.20260906.12' };
  try {
    Module._load = function(request, parent, isMain) {
      if (request === 'electron') return { app };
      if (request === 'fs' && parent?.filename === updaterPath) return { ...fs,
        readFileSync: () => publicKey.export({ type: 'spki', format: 'pem' }) };
      if (request === 'https' && parent?.filename === updaterPath) return {
        get(_url, _options, callback) {
          const req = new EventEmitter(); req.setTimeout = () => {}; req.destroy = () => {};
          queueMicrotask(() => {
            const res = new EventEmitter(); res.statusCode = 200; res.headers = {};
            res.setEncoding = () => {}; callback(res);
            res.emit('data', JSON.stringify(manifest)); res.emit('end');
          });
          return req;
        }
      };
      return originalLoad.call(this, request, parent, isMain);
    };
    delete require.cache[updaterPath];
    const updater = require('../../app/electron/updates/updater');
    function signed(version) {
      const data = { version, platforms: { [channel]: {
        url: `https://releases.ssbmnucleus.net/mock.${ext}`, size: 1, sha256: 'a'.repeat(64) } } };
      return { ...data, signature: { algorithm: 'ed25519', value: crypto.sign(null,
        Buffer.from(updater._test.canonicalJson(data)), privateKey).toString('base64') } };
    }
    manifest = signed('0.8.2');
    assert.equal((await updater.check()).version, '0.8.2');
    assert.equal(updater.getCached().version, '0.8.2');
    manifest = signed('0.8.1');
    assert.equal(await updater.check(), null);
    assert.equal(updater.getCached(), null);
    manifest = signed('0.8.2'); manifest.version = '0.8.3';
    await assert.rejects(updater.check(), /signature verification failed/);
  } finally {
    Module._load = originalLoad;
    if (cachedModule) require.cache[updaterPath] = cachedModule;
    else delete require.cache[updaterPath];
  }
});
