/**
 * Signed in-app updater.
 *
 * The release manifest is authenticated with an embedded Ed25519 public key.
 * Each artifact also has a mandatory SHA-256 and byte length, and production
 * downloads are pinned to the HTTPS releases origin.
 *
 * Channels: stable builds poll `<platform>/latest.json` only. A test build
 * (packaged previewFeatures, or a prerelease version) that was also packaged
 * with a secret `previewChannel` token (build.bat's NUCLEUS_PREVIEW_CHANNEL)
 * polls `<platform>/preview/<token>/latest.json` as well, written by
 * `tools/build/prerelease_to_r2.py --channel <token>`, and installs whichever
 * signed offer is newest by SemVer precedence. The token exists only in the
 * packaged manifest of such a build, so no other build can locate the channel.
 */
const { app } = require('electron');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn } = require('child_process');
const { compareVersions, isManifestVersion, isPrerelease } = require('./update-version');

const IS_WINDOWS = process.platform === 'win32';
const IS_MAC = process.platform === 'darwin';
// The platform folder in the releases bucket (not the stable/preview channel).
const PLATFORM_FOLDER = IS_WINDOWS ? 'windows' : IS_MAC ? 'mac' : 'linux';
const RELEASES_HOST = 'releases.ssbmnucleus.net';
const TELEMETRY_HOST = 'nttxcjrnqccogsibeqzz.supabase.co';
const TELEMETRY_PATH = '/rest/v1/rpc/api_track_app_update';
// Supabase publishable anon key. This already ships in the app's account
// service; RLS and the aggregate-only RPC are the security boundary.
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50dHhjanJucWNjb2dzaWJlcXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAyMDY3NTYsImV4cCI6MjA3NTc4Mjc1Nn0.5EJaMlem2rASzuttx1_PtwGd2cuyAOtM8VJmwwiEudo';
const TELEMETRY_TIMEOUT_MS = 1500;
const PLATFORM_KEY = IS_WINDOWS ? 'windows-x86_64'
  : IS_MAC ? 'mac-arm64'
  : 'linux-x86_64';
const DOWNLOAD_NAME = IS_WINDOWS ? 'update.exe' : IS_MAC ? 'update.dmg' : 'update.AppImage';
const MAX_MANIFEST_BYTES = 1024 * 1024;
// Upper bound for one manifest fetch, redirects and body included, so one
// stalled channel can never hold up the other channel's offer.
const MANIFEST_TIMEOUT_MS = 30000;
let manifestTimeoutMs = MANIFEST_TIMEOUT_MS;
const MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024;
const WINDOWS_SPAWN_RETRY_DELAYS_MS = [150, 300, 600, 1200, 2400, 4800];
const PUBLIC_KEY_PATH = !app.isPackaged && process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH
  ? path.resolve(process.env.NUCLEUS_UPDATE_PUBLIC_KEY_PATH)
  : path.join(__dirname, 'update-public-key.pem');

let cachedUpdate = null;
let installing = false;
// The environment Nucleus was launched with, before main applied its managed
// data root. Installers and relaunches start from it: an inherited
// NUCLEUS_DATA_ROOT would read as a user override and skip a scheduled move.
let launchEnvironment = null;

function setLaunchEnvironment(env) {
  launchEnvironment = { ...env };
}

function stableManifestUrl(platformFolder = PLATFORM_FOLDER) {
  return `https://${RELEASES_HOST}/${platformFolder}/latest.json`;
}

function previewManifestUrl(token, platformFolder = PLATFORM_FOLDER) {
  return `https://${RELEASES_HOST}/${platformFolder}/preview/${token}/latest.json`;
}

// [A-Za-z0-9_-]{16,64}, with at least one letter: electron-builder's CLI parses
// an all-digit --config.extraMetadata value as a number, which would lose it.
const PREVIEW_CHANNEL_TOKEN = /^(?=[0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,64}$/;

function previewChannelToken(packageJson) {
  const token = packageJson && packageJson.previewChannel;
  return typeof token === 'string' && PREVIEW_CHANNEL_TOKEN.test(token) ? token : null;
}

function hasPreviewFeatures(packageJson) {
  const features = packageJson && packageJson.previewFeatures;
  if (Array.isArray(features)) {
    return features.some((feature) => typeof feature === 'string' && feature.trim());
  }
  // build.bat writes it with --config.extraMetadata, which yields a string.
  return typeof features === 'string' && features.trim().length > 0;
}

// A test build is one packaged with previewFeatures (build.bat's
// NUCLEUS_PREVIEW_FEATURES) or one whose version carries a prerelease tag
// (NUCLEUS_BUILD_VERSION=0.9.0-preview.8). Only a test build with a
// prerelease version AND a previewChannel token reads a preview manifest.
function isPreviewBuild({ packageJson, version }) {
  return hasPreviewFeatures(packageJson) || isPrerelease(version);
}

// Which signed manifests this build polls, in tie-break order (the first
// source wins when two offer the same version). A stable build reads the
// public manifest only, and only accepts plain X.Y.Z from it. A test build
// with a previewChannel token reads its secret preview manifest AND the public
// one, so a newer stable release (0.9.0 after 0.9.0-preview.N) moves testers
// back to the stable channel. That return trip needs the build's own version
// to be a prerelease: a "preview" packaged as plain 0.9.0 would never see
// stable 0.9.0 as newer, so a token on a plain version is ignored (build.bat
// refuses to package one). A test build without a token (or with a malformed
// one) reads the public manifest only.
function resolveUpdateSources({ isPackaged, env = {}, packageJson = {}, version,
  platformFolder = PLATFORM_FOLDER }) {
  if (!isPackaged && env.NUCLEUS_UPDATE_MANIFEST_URL) {
    return [{ channel: 'override', url: env.NUCLEUS_UPDATE_MANIFEST_URL, allowPrerelease: true }];
  }
  const stable = { channel: 'stable', url: stableManifestUrl(platformFolder), allowPrerelease: false };
  const token = previewChannelToken(packageJson);
  if (!token || !isPrerelease(version) || !isPreviewBuild({ packageJson, version })) {
    return [stable];
  }
  return [stable, {
    channel: 'preview', url: previewManifestUrl(token, platformFolder), allowPrerelease: true,
  }];
}

function readPackageJson() {
  try {
    // Packaged: the asar root manifest, including build.bat's extraMetadata.
    return require('../../package.json');
  } catch {
    return {};
  }
}

function currentUpdateSources(version) {
  return resolveUpdateSources({
    isPackaged: app.isPackaged,
    env: process.env,
    packageJson: readPackageJson(),
    version,
  });
}

function canonicalJson(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('Manifest contains a non-finite number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(
      (key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    ).join(',')}}`;
  }
  throw new Error('Manifest contains an unsupported value');
}

function verifyManifestSignature(manifest) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new Error('Update manifest must be an object');
  }
  const signature = manifest.signature;
  if (!signature || signature.algorithm !== 'ed25519'
    || typeof signature.value !== 'string'
    || !/^[A-Za-z0-9+/]+={0,2}$/.test(signature.value)) {
    throw new Error('Update manifest is not signed');
  }
  const signatureBytes = Buffer.from(signature.value, 'base64');
  if (signatureBytes.length !== 64) {
    throw new Error('Update manifest signature is malformed');
  }
  const unsigned = { ...manifest };
  delete unsigned.signature;
  const publicKey = fs.readFileSync(PUBLIC_KEY_PATH, 'utf8');
  const verified = crypto.verify(
    null,
    Buffer.from(canonicalJson(unsigned), 'utf8'),
    publicKey,
    signatureBytes,
  );
  if (!verified) throw new Error('Update manifest signature verification failed');
  return unsigned;
}

function allowedNetworkUrl(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error('Update URL is invalid');
  }
  if (url.username || url.password || url.hash) {
    throw new Error('Update URL contains forbidden components');
  }
  if (url.protocol === 'https:' && url.hostname === RELEASES_HOST) return url;
  const localDev = !app.isPackaged
    && (url.hostname === '127.0.0.1' || url.hostname === 'localhost')
    && (url.protocol === 'http:' || url.protocol === 'https:');
  if (localDev) return url;
  throw new Error('Update URL must use the trusted releases origin');
}

function requestModule(url) {
  return url.protocol === 'http:' ? http : https;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Best-effort aggregate telemetry. Resolves on every outcome: a reporting
// outage must never turn a verified update into a failed update.
function trackCompletedUpdate(version, requestImpl = https.request) {
  const payload = Buffer.from(JSON.stringify({
    p_version: version,
    p_platform: PLATFORM_KEY,
  }));

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };

    let req;
    try {
      req = requestImpl({
        protocol: 'https:',
        hostname: TELEMETRY_HOST,
        port: 443,
        path: TELEMETRY_PATH,
        method: 'POST',
        headers: {
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          'Content-Type': 'application/json',
          'Content-Length': payload.length,
          Prefer: 'return=minimal',
        },
      }, (res) => {
        res.resume();
        res.once('end', finish);
        res.once('error', finish);
      });
    } catch {
      finish();
      return;
    }

    req.once('error', finish);
    req.setTimeout(TELEMETRY_TIMEOUT_MS, () => {
      req.destroy();
      finish();
    });
    req.end(payload);
  });
}

function spawnDetachedOnce(executable, args, spawnImpl = spawn) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawnImpl(executable, args, {
        detached: true, stdio: 'ignore', env: launchEnvironment || process.env,
      });
    } catch (error) {
      reject(error);
      return;
    }

    const onError = (error) => {
      child.removeListener('spawn', onSpawn);
      reject(error);
    };
    const onSpawn = () => {
      child.removeListener('error', onError);
      child.unref();
      resolve(child);
    };
    child.once('error', onError);
    child.once('spawn', onSpawn);
  });
}

async function spawnDetachedWithRetry(
  executable,
  args = [],
  spawnImpl = spawn,
  retryDelays = WINDOWS_SPAWN_RETRY_DELAYS_MS,
) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await spawnDetachedOnce(executable, args, spawnImpl);
    } catch (error) {
      if (!IS_WINDOWS || error.code !== 'EBUSY' || attempt >= retryDelays.length) {
        throw error;
      }
      const retryDelay = retryDelays[attempt];
      console.warn(
        `[Updater] Installer is temporarily busy; retrying in ${retryDelay}ms `
        + `(${attempt + 1}/${retryDelays.length})`
      );
      await delay(retryDelay);
    }
  }
}

// Fetch one manifest. Settles exactly once: redirect validation, HTTP, body
// and parse failures all REJECT (a throw inside a response callback would
// leave the promise pending forever). ONE deadline bounds the whole fetch --
// every redirect hop and a trickling body included. Following a redirect
// retires the previous hop: its request and response are destroyed and its
// late events are ignored, so only the current hop can settle the promise.
function fetchJson(rawUrl, { timeoutMs = manifestTimeoutMs, redirects = 3 } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let currentReq = null;
    const finish = (settle, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      settle(value);
    };
    const fail = (error) => {
      if (currentReq) currentReq.destroy();
      finish(reject, error);
    };
    const deadline = setTimeout(() => fail(new Error('Update check timed out')), timeoutMs);
    if (deadline.unref) deadline.unref();

    const get = (target, redirectsLeft) => {
      let url;
      try {
        url = allowedNetworkUrl(target);
      } catch (error) {
        fail(error);
        return;
      }
      let retired = false;
      const live = () => !settled && !retired;
      const hopFail = (error) => {
        if (live()) fail(error);
      };
      let req;
      try {
        req = requestModule(url).get(url, {
          headers: { 'Cache-Control': 'no-cache', Accept: 'application/json' },
        }, (res) => {
          res.on('error', hopFail);
          if (!live()) {
            res.destroy();
            return;
          }
          if (res.statusCode >= 300 && res.statusCode < 400
            && res.headers.location && redirectsLeft > 0) {
            let next;
            try {
              next = new URL(res.headers.location, url).toString();
            } catch {
              res.destroy();
              fail(new Error('Update URL is invalid'));
              return;
            }
            // Retire this hop before starting the next: nothing it does from
            // here on (a stalled body, a late error) may touch the new one.
            retired = true;
            res.destroy();
            req.destroy();
            get(next, redirectsLeft - 1);
            return;
          }
          if (res.statusCode !== 200) {
            res.resume();
            fail(new Error(`Update server returned HTTP ${res.statusCode}`));
            return;
          }
          let body = '';
          let bytes = 0;
          res.setEncoding('utf8');
          res.on('data', (chunk) => {
            if (!live()) return;
            bytes += Buffer.byteLength(chunk);
            if (bytes > MAX_MANIFEST_BYTES) {
              res.destroy();
              fail(new Error('Update manifest is too large'));
              return;
            }
            body += chunk;
          });
          res.on('end', () => {
            if (!live()) return;
            try {
              finish(resolve, JSON.parse(body));
            } catch {
              fail(new Error('Update manifest is not valid JSON'));
            }
          });
        });
      } catch (error) {
        fail(error);
        return;
      }
      currentReq = req;
      // Late errors from a retired hop (including the socket errors its
      // destroy() can raise) are swallowed here, never routed to fail().
      req.on('error', hopFail);
    };
    get(rawUrl, redirects);
  });
}

function downloadFile(rawUrl, destPath, expectedSize, onProgress, redirectsLeft = 3) {
  const url = allowedNetworkUrl(rawUrl);
  return new Promise((resolve, reject) => {
    const req = requestModule(url).get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400
        && res.headers.location && redirectsLeft > 0) {
        res.resume();
        // A redirect to a bad or untrusted URL must reject, not throw inside
        // this callback where nothing would ever settle the promise.
        try {
          const redirect = new URL(res.headers.location, url).toString();
          resolve(downloadFile(redirect, destPath, expectedSize, onProgress, redirectsLeft - 1));
        } catch (error) {
          reject(error);
        }
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`Download failed: HTTP ${res.statusCode}`));
        return;
      }
      const declaredSize = Number(res.headers['content-length'] || 0);
      if (declaredSize && declaredSize !== expectedSize) {
        res.resume();
        reject(new Error('Download length does not match the signed manifest'));
        return;
      }

      let received = 0;
      let settled = false;
      let completedResult = null;
      const hash = crypto.createHash('sha256');
      const out = fs.createWriteStream(destPath, { flags: 'wx', mode: 0o600 });
      const fail = (error) => {
        if (settled) return;
        settled = true;
        res.destroy();
        out.destroy();
        fs.unlink(destPath, () => reject(error));
      };

      res.on('data', (chunk) => {
        received += chunk.length;
        if (received > expectedSize) {
          fail(new Error('Download exceeds the signed size'));
          return;
        }
        hash.update(chunk);
        if (onProgress) onProgress(received, expectedSize);
      });
      res.on('aborted', () => fail(new Error('Download was interrupted')));
      res.on('error', fail);
      out.on('error', fail);
      out.on('finish', () => {
        if (settled) return;
        if (received !== expectedSize) {
          fail(new Error(`Downloaded installer is incomplete (${received} of ${expectedSize} bytes)`));
          return;
        }
        completedResult = { sha256: hash.digest('hex'), size: received };
      });
      // On Windows, 'finish' only means the writes were flushed. The file
      // descriptor closes afterward, and CreateProcess can report EBUSY if we
      // try to execute the installer in that gap. Resolve only once the
      // underlying handle is definitely closed.
      out.on('close', () => {
        if (settled || !completedResult) return;
        settled = true;
        resolve(completedResult);
      });
      res.pipe(out);
    });
    req.on('error', reject);
    req.setTimeout(60000, () => req.destroy(new Error('Update download timed out')));
  });
}

// allowPrerelease=false is the public channel's contract: it only ever
// carries X.Y.Z, so a prerelease published there by mistake is refused
// instead of reaching every stable install.
function validateManifest(rawManifest, { allowPrerelease = false } = {}) {
  const manifest = verifyManifestSignature(rawManifest);
  const platform = manifest.platforms && manifest.platforms[PLATFORM_KEY];
  if (!isManifestVersion(manifest.version, { allowPrerelease })
    || !platform || typeof platform.url !== 'string'
    || !/^[a-f0-9]{64}$/.test(platform.sha256 || '')
    || !Number.isSafeInteger(platform.size)
    || platform.size < 1 || platform.size > MAX_ARTIFACT_BYTES) {
    throw new Error('Update manifest is missing required signed fields');
  }
  allowedNetworkUrl(platform.url);
  const pathname = new URL(platform.url).pathname.toLowerCase();
  const expectedExtension = IS_WINDOWS ? '.exe' : IS_MAC ? '.dmg' : '.appimage';
  if (!pathname.endsWith(expectedExtension)) {
    throw new Error('Update artifact type does not match this platform');
  }
  return { manifest, platform };
}

async function fetchSource(source) {
  const manifestUrl = allowedNetworkUrl(source.url);
  manifestUrl.searchParams.set('t', String(Date.now()));
  const { manifest, platform } = validateManifest(
    await fetchJson(manifestUrl.toString()),
    { allowPrerelease: source.allowPrerelease },
  );
  return { channel: source.channel, manifest, platform };
}

// The newest valid offer across sources; ties keep the earlier source (the
// public manifest), so a release published to both channels installs as stable.
function pickNewest(offers) {
  let best = null;
  for (const offer of offers) {
    if (!best || compareVersions(offer.manifest.version, best.manifest.version) > 0) best = offer;
  }
  return best;
}

async function check() {
  const current = app.getVersion();
  const sources = currentUpdateSources(current);
  const settled = await Promise.allSettled(sources.map(fetchSource));
  const offers = [];
  const failures = [];
  settled.forEach((result, index) => {
    if (result.status === 'fulfilled') offers.push(result.value);
    else failures.push({ channel: sources[index].channel, error: result.reason });
  });
  // One unreachable or invalid channel must not hide the other; only a check
  // where every source failed is a failed check.
  if (!offers.length) throw failures[0].error;
  for (const { channel, error } of failures) {
    console.warn(`[Updater] ${channel} manifest ignored: ${error?.message || error}`);
  }
  const best = pickNewest(offers);
  const { manifest, platform } = best;
  console.log(`[Updater] current=${current} latest=${manifest.version} (${best.channel})`);
  if (compareVersions(manifest.version, current) <= 0) {
    cachedUpdate = null;
    return null;
  }
  cachedUpdate = {
    version: manifest.version,
    channel: best.channel,
    notes: typeof manifest.notes === 'string' ? manifest.notes.slice(0, 20000) : '',
    url: platform.url,
    sha256: platform.sha256,
    size: platform.size,
  };
  return cachedUpdate;
}

async function install(onProgress, overrides = {}) {
  if (!cachedUpdate) throw new Error('No update available - run a check first');
  if (installing) throw new Error('Update already in progress');
  // A concurrent check may replace/clear cachedUpdate while downloadFile is
  // awaiting network and disk. This install owns the exact signed selection
  // the user approved for its whole lifecycle.
  const selected = Object.freeze({ ...cachedUpdate });
  installing = true;
  try {
    return await installSelected(selected, onProgress, overrides);
  } finally {
    installing = false;
  }
}

async function installSelected(selected, onProgress, overrides = {}) {
  const runtime = {
    app,
    fs,
    spawn,
    spawnDetachedOnce,
    downloadFile,
    spawnDetachedWithRetry,
    trackCompletedUpdate,
    shellOpenPath: (file) => require('electron').shell.openPath(file),
    schedule: setTimeout,
    platform: process.platform,
    appImage: process.env.APPIMAGE,
    ...overrides,
  };
  const isWindows = runtime.platform === 'win32';
  const isMac = runtime.platform === 'darwin';
  const downloadName = isWindows ? 'update.exe' : isMac ? 'update.dmg' : 'update.AppImage';
  let downloadDir = null;
  try {
    downloadDir = runtime.fs.mkdtempSync(path.join(runtime.app.getPath('temp'), 'nucleus-update-'));
    const destPath = path.join(downloadDir, downloadName);
    const result = await runtime.downloadFile(
      selected.url, destPath, selected.size, onProgress
    );
    const expectedHash = Buffer.from(selected.sha256, 'hex');
    const actualHash = Buffer.from(result.sha256, 'hex');
    if (!crypto.timingSafeEqual(actualHash, expectedHash)) {
      throw new Error('Downloaded installer failed checksum verification');
    }

    // Production only: development update harnesses must not pollute the real
    // admin totals. This is awaited for at most 1.5s so app.quit cannot abort a
    // successful report, but all network failures are deliberately swallowed.
    if (runtime.app.isPackaged) await runtime.trackCompletedUpdate(selected.version);

    if (isWindows) {
      console.log('[Updater] Verified - launching installer and quitting');
      // Defender/SmartScreen can briefly reopen a freshly downloaded EXE.
      // Retry sharing violations instead of turning a transient scan into a
      // failed update.
      await runtime.spawnDetachedWithRetry(destPath);
      downloadDir = null;
      runtime.schedule(() => runtime.app.quit(), 1500);
    } else if (isMac) {
      console.log(`[Updater] Verified - revealing ${destPath}`);
      const openError = await runtime.shellOpenPath(destPath);
      if (openError) throw new Error(`Could not open downloaded update: ${openError}`);
      downloadDir = null;
      runtime.schedule(() => runtime.app.quit(), 1500);
    } else {
      const target = runtime.appImage;
      if (!target) {
        // The message sends the user to this verified file: keep it.
        downloadDir = null;
        throw new Error('Not running from an AppImage ($APPIMAGE unset); '
          + `download saved to ${destPath} - replace the app manually.`);
      }
      const staged = path.join(path.dirname(target), `.${path.basename(target)}.new`);
      runtime.fs.copyFileSync(destPath, staged);
      runtime.fs.chmodSync(staged, 0o755);
      runtime.fs.renameSync(staged, target);
      runtime.fs.rmSync(downloadDir, { recursive: true, force: true });
      downloadDir = null;
      // The replacement must be able to acquire Electron's single-instance
      // lock as it starts. Release immediately before spawn; if spawn throws,
      // reacquire so the still-running app keeps its normal lifecycle.
      runtime.app.releaseSingleInstanceLock();
      try {
        await runtime.spawnDetachedOnce(target, [], runtime.spawn);
      } catch (error) {
        runtime.app.requestSingleInstanceLock();
        throw error;
      }
      runtime.schedule(() => runtime.app.quit(), 0);
    }
  } catch (error) {
    if (downloadDir) runtime.fs.rmSync(downloadDir, { recursive: true, force: true });
    throw error;
  }
}

function getCached() {
  return cachedUpdate;
}

function setCachedUpdateForTest(value) {
  cachedUpdate = value;
}

function setManifestTimeoutForTest(ms) {
  manifestTimeoutMs = ms == null ? MANIFEST_TIMEOUT_MS : ms;
}

module.exports = {
  check,
  install,
  getCached,
  setLaunchEnvironment,
  _test: {
    canonicalJson,
    verifyManifestSignature,
    validateManifest,
    resolveUpdateSources,
    isPreviewBuild,
    pickNewest,
    allowedNetworkUrl,
    downloadFile,
    spawnDetachedWithRetry,
    trackCompletedUpdate,
    installSelected,
    setCachedUpdateForTest,
    setManifestTimeoutForTest,
    fetchJson,
  },
};
