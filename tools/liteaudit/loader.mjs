// Node-only adapters. The production paint source is never edited or copied.
import { readFile } from 'node:fs/promises';
const replays = new URL('../../app/frontend/src/tracker/replays/', import.meta.url);
const realStages = new URL('meleeStages.js', replays).href;
const realInference = new URL('liteStageInference.js', replays).href;
const realSparks = new URL('hitSparks.js', replays).href;
const realTrails = new URL('swordTrails.js', replays).href;
const realArt = new URL('itemArt.js', replays).href;

// Tools/tests are synchronous paint hosts. Hydrate their shared cache before
// evaluating meleeStages, while browser hosts await only the clip's stage.
export async function loadStageDataFromDisk() {
  const { registerStageDataLoader, registerFighterDataLoader, registerItemDataLoader, registerHitDataLoader, ensureItemData, ITEM_IDS, ensureFighterData, ensureHitData, FIGHTER_IDS, ensureStageData, STAGE_SIM_IDS } = await import(new URL('stageData.js', replays));
  registerStageDataLoader(async id => JSON.parse(await readFile(new URL(`data/stages/${id}.json`, replays), 'utf8')));
  registerFighterDataLoader(async id => JSON.parse(await readFile(new URL(`data/fighters/${id}.json`, replays), 'utf8')));
  registerItemDataLoader(async id => JSON.parse(await readFile(new URL(`data/items/${id}.json`, replays), 'utf8')));
  registerHitDataLoader(async id => JSON.parse(await readFile(new URL(`data/hits/${id}.json`, replays), 'utf8')));
  await Promise.all(ITEM_IDS.map(async id => {
    if (!await ensureItemData(id)) throw new Error(`Item ${id} disk data unavailable`);
  }));
  await Promise.all(FIGHTER_IDS.map(async id => {
    if (!await ensureFighterData(id)) throw new Error(`Fighter ${id} disk data unavailable`);
    if (!await ensureHitData(id)) throw new Error(`Fighter ${id} hit table unavailable`);
  }));
  const core = JSON.parse(await readFile(new URL('data/stageCollision.json', replays), 'utf8'));
  const ids = new Set([...STAGE_SIM_IDS, ...Object.entries(core.stages).filter(([, data]) => data.deferred).map(([id]) => Number(id))]);
  await Promise.all([...ids].map(async id => {
      if (!await ensureStageData(id)) throw new Error(`Stage ${id} disk data unavailable`);
    }));
}

export async function resolve(specifier, context, nextResolve) {
  if (context.parentURL?.startsWith(replays.href)) {
    if (specifier === '../../shared/config/config') return { url: 'liteaudit:config', shortCircuit: true };
    if (specifier === '../../shared/transport/api') return { url: 'liteaudit:api', shortCircuit: true };
    if (context.parentURL.endsWith('/litePaint.js') && /^\.\/meleeStages(?:\.js)?$/.test(specifier))
      return { url: 'liteaudit:stages', shortCircuit: true };
    if (context.parentURL.endsWith('/litePaint.js') && /^\.\/liteStageInference(?:\.js)?$/.test(specifier))
      return { url: 'liteaudit:inference', shortCircuit: true };
    if (context.parentURL.endsWith('/litePaint.js') && /^\.\/hitSparks(?:\.js)?$/.test(specifier))
      return { url: 'liteaudit:sparks', shortCircuit: true };
    if (context.parentURL.endsWith('/litePaint.js') && /^\.\/swordTrails(?:\.js)?$/.test(specifier))
      return { url: 'liteaudit:trails', shortCircuit: true };
    if (context.parentURL.endsWith('/litePaint.js') && /^\.\/itemArt(?:\.js)?$/.test(specifier))
      return { url: 'liteaudit:art', shortCircuit: true };
    if (specifier.startsWith('./') && !/\.(?:js|json)$/.test(specifier))
      return nextResolve(`${specifier}.js`, context);
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  let source;
  if (url === realStages || (url.startsWith(new URL('stageSim/', replays).href) && /\/stage\d+\.js$/.test(url))) source = `
    import { loadStageDataFromDisk } from ${JSON.stringify(import.meta.url)};
    await loadStageDataFromDisk();
    ${await readFile(new URL(url), 'utf8')}
  `;
  if (url === 'liteaudit:config') source = 'export const BACKEND_URL = "offline:audit";';
  if (url === 'liteaudit:api') source = 'export const api = {get() { throw new Error("Network API called during offline audit"); }};';
  if (url === 'liteaudit:stages') source = `
    export * from ${JSON.stringify(realStages)};
    import * as real from ${JSON.stringify(realStages)};
    export function moverSegments(stage, frame) {
      globalThis.__liteauditStageCalls?.push({kind:'movers', stage, frame});
      return real.moverSegments(stage, frame);
    }
    export function collisionGeometry(stage, frame) {
      globalThis.__liteauditStageCalls?.push({kind:'collision', stage, frame});
      return real.collisionGeometry(stage, frame);
    }
    export function randallPlatform(frame) {
      globalThis.__liteauditStageCalls?.push({kind:'randall', frame});
      return real.randallPlatform(frame);
    }
  `;
  // A simulator may read item histories while paint computes the stage, and
  // the render check labels item draws by those reads. Tell it when the stage
  // geometry is done so the stage pass keeps its own label.
  if (url === 'liteaudit:inference') source = `
    export * from ${JSON.stringify(realInference)};
    import * as real from ${JSON.stringify(realInference)};
    export function stageGeometryAt(bundle, idx) {
      const result = real.stageGeometryAt(bundle, idx);
      globalThis.__liteauditAfterStageGeometry?.();
      return result;
    }
  `;
  // A burst or a breaking egg is drawn after the fighters, labelled by its
  // item's record read just before; what paint draws after it is not that item's.
  if (url === 'liteaudit:art') source = `
    export * from ${JSON.stringify(realArt)};
    import * as real from ${JSON.stringify(realArt)};
    export function drawExplosion(ctx, ...rest) {
      try { return real.drawExplosion(ctx, ...rest); } finally { ctx.tag = 'after-items'; }
    }
    export function drawEggBreak(ctx, ...rest) {
      try { return real.drawEggBreak(ctx, ...rest); } finally { ctx.tag = 'after-items'; }
    }
  `;
  // The render check labels the hit spark pass by the call that draws it.
  if (url === 'liteaudit:sparks') source = `
    export * from ${JSON.stringify(realSparks)};
    import * as real from ${JSON.stringify(realSparks)};
    export function drawHitSparks(ctx, ...rest) {
      const tag = ctx.tag;
      ctx.tag = 'spark';
      try { return real.drawHitSparks(ctx, ...rest); } finally { ctx.tag = tag; }
    }
  `;
  // ... and the sword trails' pass the same way.
  if (url === 'liteaudit:trails') source = `
    export * from ${JSON.stringify(realTrails)};
    import * as real from ${JSON.stringify(realTrails)};
    export function drawSwordTrails(ctx, ...rest) {
      const tag = ctx.tag;
      ctx.tag = 'trail';
      try { return real.drawSwordTrails(ctx, ...rest); } finally { ctx.tag = tag; }
    }
  `;
  // Vite's JSON imports omit Node's import attributes. Export the unchanged data
  // as ESM here, scoped to replay geometry only.
  if (url.startsWith(replays.href) && url.endsWith('.json'))
    source = `export default ${await readFile(new URL(url), 'utf8')};`;
  if (source != null) return { format: 'module', source, shortCircuit: true };
  return nextLoad(url, context);
}
