'use strict';

// No Electron dependency: the host owns dialogs, trusted IPC and startup order.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

const MARKER = '.nucleus-data-location.json';
function defaultDataRoot({ platform = process.platform, env = process.env, home = os.homedir() } = {}) {
  if (platform === 'win32') return path.join(env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'SSBM Nucleus');
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'SSBM Nucleus');
  return path.join(home, '.melee-nexus');
}
function contains(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}
async function exists(file) {
  try { await fs.lstat(file); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
async function safePath(raw, { missingLeaf = false } = {}) {
  if (typeof raw !== 'string' || !raw.trim() || !path.isAbsolute(raw) || raw.includes('\0')) throw new Error('Choose an absolute local folder path.');
  const resolved = path.resolve(raw);
  if (resolved === path.parse(resolved).root) throw new Error('Choose a dedicated data folder, not a drive root.');
  if (process.platform === 'win32' && (resolved.startsWith('\\\\') || resolved.slice(2).includes(':'))) throw new Error('Choose a local drive folder, not a network or device path.');
  // Reject links/junctions at every existing ancestor, including the leaf.
  for (let current = resolved; ; current = path.dirname(current)) {
    try {
      const stat = await fs.lstat(current);
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error(`Storage path is not an ordinary directory: ${current}`);
    } catch (error) {
      if (!(error.code === 'ENOENT' && missingLeaf && current === resolved)) throw error;
    }
    if (current === path.dirname(current)) break;
  }
  return resolved;
}
async function writable(folder) {
  const probe = path.join(folder, `.nucleus-write-check-${crypto.randomUUID()}`);
  const handle = await fs.open(probe, 'wx', 0o600);
  try { await handle.writeFile('storage check'); await handle.sync(); }
  finally { await handle.close(); await fs.unlink(probe); }
}
async function atomicJson(file, value) {
  const temp = `${file}.${crypto.randomUUID()}.tmp`;
  const handle = await fs.open(temp, 'wx', 0o600);
  try { await handle.writeFile(JSON.stringify(value, null, 2)); await handle.sync(); }
  finally { await handle.close(); }
  try { await fs.rename(temp, file); }
  catch (error) { await fs.unlink(temp).catch(() => {}); throw error; }
}

class StorageLocationManager {
  constructor({ bootstrapDir, defaultRoot = defaultDataRoot(), migrate, onProgress = () => {}, disabledReason = null }) {
    this.file = path.join(bootstrapDir, 'storage-location.json');
    this.defaultRoot = path.resolve(defaultRoot);
    this.migrate = migrate;
    this.onProgress = onProgress;
    this.disabledReason = disabledReason;
    this.busy = false;
    this.state = null;
    this.progress = null;
  }
  async load() {
    if (this.state) return this.state;
    try {
      const state = JSON.parse(await fs.readFile(this.file, 'utf8'));
      if (state.version !== 1 || !state.active || typeof state.active.root !== 'string' || !path.isAbsolute(state.active.root)) throw new Error('Invalid storage bootstrap setting.');
      if (state.previous && (typeof state.previous.root !== 'string' || !path.isAbsolute(state.previous.root))) throw new Error('Invalid previous storage location.');
      if (state.pending && (!/^[0-9a-f-]{36}$/.test(state.pending.id)
          || !['scheduled', 'copying', 'verified', 'failed'].includes(state.pending.phase)
          || !['source', 'stage', 'target'].every(key => typeof state.pending[key] === 'string' && path.isAbsolute(state.pending[key])))) throw new Error('Invalid pending storage move.');
      this.state = state;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      this.state = { version: 1, active: { root: this.defaultRoot }, pending: null, previous: null };
      this.firstUse = true;
    }
    return this.state;
  }
  async save(next) {
    await fs.mkdir(path.dirname(this.file), { recursive: true });
    await atomicJson(this.file, next);
    this.state = next;
    this.firstUse = false;
  }
  async status() {
    const state = await this.load();
    return { currentRoot: state.active.root, scratchRoot: path.join(state.active.root, 'scratch'),
      pending: state.pending, previousRoot: state.previous?.root || null,
      progress: this.progress, busy: this.busy, disabledReason: this.disabledReason };
  }
  async exclusive(fn) {
    if (this.busy) throw new Error('A storage operation is already running.');
    this.busy = true;
    try { return await fn(); } finally { this.busy = false; }
  }
  async validateDestination(source, raw) {
    const target = await safePath(raw, { missingLeaf: true });
    if (contains(source, target) || contains(target, source)) throw new Error('The new folder must be separate from the current data folder.');
    const profile = path.resolve(path.dirname(this.file));
    if (contains(target, profile) || contains(profile, target)) throw new Error('The data folder must be separate from the application profile.');
    if (await exists(target) && (await fs.readdir(target)).length) throw new Error('The destination must be a new or completely empty folder.');
    await writable(await exists(target) ? target : path.dirname(target));
    return target;
  }
  async schedule(raw) {
    return this.exclusive(async () => {
      if (this.disabledReason) throw new Error(this.disabledReason);
      const state = await this.load();
      if (state.pending) throw new Error('Cancel the scheduled move before choosing another folder.');
      const source = await safePath(state.active.root);
      const target = await this.validateDestination(source, raw);
      const id = crypto.randomUUID();
      const pending = { id, source, target, stage: path.join(path.dirname(target), `.nucleus-move-${id}`), phase: 'scheduled' };
      await this.save({ ...state, pending });
      return this.status();
    });
  }
  async cancel() {
    return this.exclusive(async () => {
      const state = await this.load();
      // Partial/verified copies remain untouched, available for manual recovery.
      await this.save({ ...state, pending: null });
      return this.status();
    });
  }
  async checkActive(active) {
    const root = await safePath(active.root);
    if (active.identity) {
      const marker = JSON.parse(await fs.readFile(path.join(root, MARKER), 'utf8'));
      if (marker.identity !== active.identity) throw new Error('The selected data folder is missing or belongs to another library. Reconnect the original drive.');
    }
    await writable(root);
    return root;
  }
  async rollback() {
    return this.exclusive(async () => {
      const state = await this.load();
      if (!state.previous) throw new Error('There is no previous data location.');
      await this.checkActive(state.previous);
      await this.save({ ...state, active: state.previous, previous: state.active, pending: null });
      return this.status();
    });
  }
  async prepareLaunch() {
    return this.exclusive(async () => {
      let state = await this.load();
      if (this.disabledReason) return {};
      if (state.pending) {
        const pending = state.pending;
        if (pending.phase !== 'scheduled') throw new Error(`Storage move was interrupted or failed. Original data is retained at ${pending.source}. Cancel the pending move to use it, or choose a new empty folder. Partial copy: ${pending.stage}. ${pending.error || ''}`);
        let migration = null;
        let activated = false;
        try {
          await this.checkActive(state.active);
          const target = await this.validateDestination(state.active.root, pending.target);
          if (pending.source !== state.active.root || pending.stage !== path.join(path.dirname(target), `.nucleus-move-${pending.id}`)) throw new Error('Invalid pending storage move.');
          if (await exists(pending.stage)) throw new Error('An interrupted copy already exists. Cancel and choose a fresh destination.');
          await this.save({ ...state, pending: { ...pending, phase: 'copying' } });
          migration = await this.migrate({ source: pending.source, stage: pending.stage, target,
            onProgress: (progress) => { this.progress = progress; this.onProgress(progress); } });
          if (migration?.phase !== 'verified') throw new Error('Storage worker did not verify the copied data.');
          await safePath(pending.stage);
          await atomicJson(path.join(pending.stage, MARKER), { identity: pending.id, source: pending.source });
          await this.save({ ...this.state, pending: { ...pending, phase: 'verified' } });
          // Revalidate immediately before publication; rmdir can only remove an empty directory.
          await this.validateDestination(pending.source, target);
          if (await exists(target)) await fs.rmdir(target);
          await fs.rename(pending.stage, target);
          const active = { root: target, identity: pending.id };
          await this.checkActive(active);
          migration.assertAlive?.();
          await this.save({ version: 1, active, previous: state.active, pending: null });
          activated = true;
          state = this.state;
          await migration.release?.(true);
        } catch (error) {
          if (!activated) {
            await migration?.release?.(false).catch(() => {});
            await this.save({ ...this.state, pending: { ...this.state.pending, phase: 'failed', error: error.message } }).catch(() => {});
          }
          throw error;
        }
      }
      // Only a never-selected default root may be created. A selected missing
      // drive/library is always an error, never a fresh C: library.
      if (this.firstUse && state.active.root === this.defaultRoot && !(await exists(state.active.root))) {
        await safePath(state.active.root, { missingLeaf: true });
        await fs.mkdir(state.active.root);
      }
      const root = await this.checkActive(state.active);
      if (!state.active.identity) {
        const identity = crypto.randomUUID();
        await atomicJson(path.join(root, MARKER), { identity });
        await this.save({ ...state, active: { root, identity } });
        this.firstUse = false;
      }
      const scratch = path.join(root, 'scratch');
      await safePath(scratch, { missingLeaf: true });
      await fs.mkdir(scratch, { recursive: true });
      await writable(scratch);
      return { NUCLEUS_DATA_ROOT: root, NUCLEUS_SCRATCH_DIR: scratch,
        NUCLEUS_MANAGED_DATA_ROOT: '1', TMP: scratch, TEMP: scratch, TMPDIR: scratch };
    });
  }
}

// Host supplies its known backend executable and argument prefix. Never shell
// interpolate user paths; no server is started by this maintenance invocation.
function createMigrationRunner({ command, args = [], cwd, env = process.env }) {
  return ({ source, stage, target, onProgress = () => {} }) => new Promise((resolve, reject) => {
    const child = spawn(command, [...args, '--storage-maintenance', '--await-activation', '--source', source, '--stage', stage, '--target', target],
      { cwd, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let buffer = '', stderr = '', verified = null, workerError = '', exited = false, releasePromise = null;
    let finish;
    // This completion promise never rejects until a caller explicitly releases
    // the worker, avoiding an unhandled rejection during publication awaits.
    const completion = new Promise(resolveCompletion => { finish = resolveCompletion; });
    child.on('error', (error) => { exited = true; finish({ error }); reject(error); });
    child.stdin.on('error', (error) => { workerError = error.message; });
    const assertAlive = () => {
      if (exited || child.exitCode !== null) throw new Error('The storage worker exited before location activation.');
    };
    const release = (activate) => {
      if (releasePromise) return releasePromise;
      releasePromise = (async () => {
        assertAlive();
        child.stdin.end(activate ? 'activate\n' : 'abort\n');
        const result = await completion;
        if (activate && (result.error || result.code !== 0)) throw result.error || new Error(workerError || stderr || 'Storage worker could not finish activation.');
      })();
      return releasePromise;
    };
    const consume = (line) => {
      try {
        const progress = JSON.parse(line);
        if (progress.phase === 'verified' && !verified) {
          verified = progress;
          resolve({ ...progress, release, assertAlive });
        }
        if (progress.phase === 'error') workerError = progress.error || 'Storage worker failed.';
        onProgress(progress);
      } catch { /* non-protocol diagnostics are not success */ }
    };
    child.stdout.on('data', (chunk) => {
      buffer += chunk.toString();
      let end;
      while ((end = buffer.indexOf('\n')) !== -1) { consume(buffer.slice(0, end)); buffer = buffer.slice(end + 1); }
      if (buffer.length > 65536) buffer = buffer.slice(-65536);
    });
    child.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-4000); });
    child.on('close', (code) => {
      exited = true;
      finish({ code });
      if (buffer.trim()) consume(buffer);
      if (!verified) reject(new Error(workerError || stderr.trim() || `Storage verification failed (exit ${code}). Original data has not been removed.`));
    });
  });
}

module.exports = { StorageLocationManager, createMigrationRunner, defaultDataRoot, safePath, MARKER };
