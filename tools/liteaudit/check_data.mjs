import path from 'node:path';
import { args, outDir, selection, readJSON, writeJSON, produce, Flags, FLOAT_FIELDS,
  different, trueFrame, itemFrames, matchItems, direct } from './common.mjs';

function compareFighters(actual, expected, rowFor, truth, flags) {
  const compare = (key, port, a, e) => {
    if (e == null || a == null) {
      if (e !== a) flags.flag('fighter_field', { field: key, port, expected: e == null ? null : 'series', actual: a == null ? null : 'series' });
      return;
    }
    for (let j = 0; j < e.length; j++) {
      const row = rowFor(truth.frame_ids[j]);
      const value = a[row];
      flags.metric('fighter_values_compared');
      if (different(value, e[j], FLOAT_FIELDS.has(key) ? .05 : 0)) {
        flags.flag('fighter_field', { field: key, port, frame: truth.frame_ids[j], row, expected: e[j], actual: value });
        flags.metric(`fighter_delta.${key}`);
      }
    }
  };
  for (const [key, ports] of Object.entries(expected)) {
    if (key === 'fol') continue;
    if ((actual[key]?.length ?? 0) !== ports.length) flags.flag('fighter_shape', { field: key, expectedPorts: ports.length, actualPorts: actual[key]?.length });
    ports.forEach((series, port) => compare(key, port, actual[key]?.[port], series));
  }
  const ef = expected.fol || [], af = actual.fol || [];
  if (ef.length !== af.length) flags.flag('follower_shape', { expected: ef.length, actual: af.length });
  for (const e of ef) {
    const a = af.find(f => f.of === e.of);
    for (const [key, series] of Object.entries(e)) if (key !== 'of') compare(key, `follower:${e.of}`, a?.[key], series);
  }
}

function compareItemSet(expected, actual, frame, flags, prefix) {
  const { pairs, missing, extra } = matchItems(expected, actual);
  for (const e of missing) flags.flag(`${prefix}_missing`, { frame, ...e });
  for (const a of extra) flags.flag(`${prefix}_extra`, { frame, ...a });
  for (const [e, a] of pairs) {
    for (const key of ['x', 'y', 'd', 's']) if (different(a[key], e[key], key === 'x' || key === 'y' ? .05 : 0))
      flags.flag(`${prefix}_field`, { frame, type: e.t, field: key, expected: e[key], actual: a[key] });
    if (prefix === 'raw_item') {
      flags.metric('item_samples');
      if (!Number.isFinite(a.vx) || !Number.isFinite(a.vy)) flags.flag('item_velocity_unavailable', { frame, type: e.t });
      else {
        flags.metric('item_velocity_available');
        for (const key of ['vx', 'vy']) if (different(a[key], e[key], 1e-5))
          flags.flag('item_velocity_delta', { frame, type: e.t, field: key, expected: e[key], actual: a[key] });
      }
    }
  }
}

function compareStage(actual, expected, flags, check) {
  for (const kind of ['fod', 'stadium']) {
    const aa = actual[kind] || [], ee = expected[kind] || [];
    flags.metric(`${check}.${kind}.events`, ee.length);
    if (aa.length !== ee.length) flags.flag(check, { stage: kind, expectedCount: ee.length, actualCount: aa.length });
    for (let i = 0; i < Math.max(aa.length, ee.length); i++) {
      if (!aa[i] || !ee[i] || ee[i].some((value, j) => different(value, aa[i]?.[j], kind === 'fod' && j === 2 ? .05 : 0)))
        flags.flag(check, { stage: kind, event: i, expected: ee[i], actual: aa[i] });
    }
  }
}

export function checkData(bundle, rowFids, truth) {
  const flags = new Flags(), n = bundle.meta.n, raw = truth.raw;
  flags.metric('rows', n);
  flags.metric('raw_unique_frames', raw.unique_frames);
  const expectedIds = truth.frame_ids || raw.frame_ids;
  const last = new Map(rowFids?.map((f, i) => [f, i]));
  const rowFor = frame => rowFids ? last.get(frame) : frame - bundle.meta.start_frame;
  const duplicates = rowFids ? rowFids.length - new Set(rowFids).size : Math.max(0, n - raw.unique_frames);
  if (duplicates) flags.flag('rollback_rows', { rows: n, uniqueFrames: raw.unique_frames }, duplicates);
  if (n !== raw.unique_frames) flags.flag('timeline_row_count', { rows: n, uniqueFrames: raw.unique_frames });
  if (!bundle.meta.finalized) flags.flag('not_finalized', { version: bundle.meta.v });
  if (bundle.meta.finalized) {
    for (let idx = 0; idx < Math.max(n, expectedIds.length); idx++) {
      flags.metric('finalized_basis_rows');
      if (bundle.meta.start_frame + idx !== expectedIds[idx]) flags.flag('finalized_frame_basis',
        { idx, claimedFrame: bundle.meta.start_frame + idx, trueFrame: expectedIds[idx] });
    }
  }
  for (const [key, ports] of Object.entries(bundle.frames)) {
    if (key === 'fol') continue;
    for (const [port, values] of ports.entries()) if (values != null && values.length !== n)
      flags.flag('fighter_shape', { field: key, port, length: values.length, expected: n });
  }
  if (truth.bundle) compareFighters(bundle.frames, truth.bundle.frames, rowFor, truth, flags);
  else flags.flag('python_truth_unavailable', { reason: truth.python_error });
  const actualItems = itemFrames(bundle.items || []);
  const pythonItems = itemFrames(truth.bundle?.items || []);
  const rawItems = itemFrames(raw.items, t => t.start);
  for (let j = 0; j < expectedIds.length; j++) {
    const frame = expectedIds[j], row = rowFor(frame), actual = actualItems.get(row) || [];
    if (truth.bundle) compareItemSet(pythonItems.get(j) || [], actual, frame, flags, 'python_item');
    compareItemSet(rawItems.get(frame) || [], actual, frame, flags, 'raw_item');
  }
  // Track boundaries matter too: identical frame multisets can hide split lives.
  const trackKeys = (items, rows) => items.map(it => {
    const selected = [];
    for (let k = 0; k < it.x.length; k++) {
      const row = it.f + k, fr = rows ? rows[row] : bundle.meta.start_frame + row;
      if (!rows || last.get(fr) === row) selected.push(fr);
    }
    selected.sort((a, b) => a - b);
    return selected.length ? `${it.t}/${it.o}/${selected[0]}/${selected.at(-1)}/${selected.length}` : null;
  }).filter(Boolean).sort();
  if (truth.bundle) {
    const actualKeys = trackKeys(bundle.items || [], rowFids);
    const expectedKeys = (truth.bundle.items || []).map(it => `${it.t}/${it.o}/${truth.frame_ids[it.f]}/${truth.frame_ids[it.f + it.x.length - 1]}/${it.x.length}`).sort();
    if (JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) flags.flag('item_track_parity',
      { expectedTracks: expectedKeys.length, actualTracks: actualKeys.length,
        expectedExamples: expectedKeys.filter(k => !actualKeys.includes(k)).slice(0, 5), actualExamples: actualKeys.filter(k => !expectedKeys.includes(k)).slice(0, 5) });
  }
  const actualStage = Object.fromEntries(Object.entries(bundle.stage_state || {}).map(([kind, events]) =>
    [kind, events.map(e => [trueFrame(bundle, rowFids, e[0]), ...e.slice(1)])]));
  compareStage(actualStage, raw.stage, flags, 'raw_stage_timing');
  if (truth.bundle) {
    const expectedStage = Object.fromEntries(Object.entries(truth.bundle.stage_state || {}).map(([kind, events]) =>
      [kind, events.map(e => [truth.frame_ids[e[0]], ...e.slice(1)])]));
    compareStage(actualStage, expectedStage, flags, 'python_stage_timing');
  }
  for (const warning of raw.warnings || []) flags.flag('raw_warning', { warning });
  for (const warning of bundle.warnings || []) flags.flag('producer_warning', { warning });
  if (raw.missing_frames) flags.flag('raw_frame_gaps', {}, raw.missing_frames);
  return flags.result();
}

export async function main() {
  const options = args(), out = outDir(options.out), records = [];
  for (const game of selection(options, out).games) {
    try {
      const truth = readJSON(path.join(out, 'truth', `${game.id}.json.gz`));
      const { bundle, rowFids } = await produce(game, truth, options.producer || 'python', out);
      records.push({ id: game.id, path: game.path, ...checkData(bundle, rowFids, truth) });
    } catch (error) { records.push({ id: game.id, path: game.path, flags: { audit_error: { count: 1, examples: [{ error: String(error) }] } } }); }
  }
  writeJSON(path.join(out, `data-${options.producer || 'python'}-${String(options.shard || '1/1').replace('/', '-')}.json`), records);
  console.log(`Data: ${records.length} replay reports (findings never set a failing exit status)`);
}
if (direct(import.meta)) await main();
