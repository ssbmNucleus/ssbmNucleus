import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { ROOT, args, outDir, selection, readJSON, writeJSON, produce } from './common.mjs';
import { checkData } from './check_data.mjs';
import { checkRender, loadAnimations } from './check_render.mjs';

const HELP = `Watch Lite audit: highlighters, never build gates.
node tools/liteaudit/run.mjs [--producer python|js] [--full] [--shard 1/4]
  --root PATH        Replay tree (default ~/OneDrive/Documents/Slippi)
  --out PATH         Scratch directory under app/scratch/liteaudit/harness/
  --python PATH      Python with peppi_py (default app/venv/Scripts/python.exe)
  --anim-zips PATH   Local read-only animation archives
  --size 40          Target golden size (coverage can require more)
  --every 30         Render every Nth row AND every item row
  --limit N          Limit selected shard (development only)
  --refresh          Rebuild cached metadata and truth
  --skip-corpus      Reuse corpus/golden manifests (parallel runs)
  --traces N         Save N recorded draw lists per game (default 0)
  --help            Show this text
Reports include errors and unavailable checks; findings never set exit failure.
`;

function child(exe, argv) {
  return new Promise((resolve, reject) => {
    const p = spawn(exe, argv, { cwd: ROOT, windowsHide: true, stdio: 'inherit',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
    p.once('error', reject);
    p.once('exit', code => code === 0 ? resolve() : reject(new Error(`${path.basename(argv[1])} exited ${code}`)));
  });
}

function summary(records) {
  const checks = {}, metrics = {}, fallbacks = {}, worst = [];
  for (const record of records) {
    let total = 0;
    for (const [check, flag] of Object.entries(record.flags)) {
      const c = checks[check] ||= { count: 0, files: 0 };
      c.count += flag.count; c.files++; total += flag.count;
    }
    for (const [key, value] of Object.entries(record.metrics || {})) metrics[key] = (metrics[key] || 0) + value;
    for (const [key, value] of Object.entries(record.fallbacks || {})) fallbacks[key] = (fallbacks[key] || 0) + value;
    worst.push({ path: record.path, flags: total, checks: Object.keys(record.flags) });
  }
  return { checks, metrics, fallbacks, worst_files: worst.sort((a, b) => b.flags - a.flags).slice(0, 10) };
}

function markdown(report) {
  const s = report.summary, metrics = s.metrics;
  const lines = ['# Watch Lite audit (highlighters, not gates)', '',
    `Producer: **${report.producer}**. Selected: **${report.selected}**; audited: **${report.audited}**; unavailable: **${report.unavailable}**. Shard: ${report.shard}. Runtime: ${report.seconds}s.`, '',
    `Sampling: every ${report.every}th row plus **all item rows**. ${metrics.sampled_frames || 0} frames; ${metrics.live_item_draw_checks || 0} live item checks; ${metrics.laser_segments_checked || 0} laser segments; ${metrics.silhouettes || 0} silhouettes; ${metrics.dot_fallbacks || 0} dot fallbacks.`, '',
    `Live fighters (state > 10): ${metrics.live_dot_fallbacks || 0} dot fallbacks / ${metrics.live_fighters_drawn || 0} draws.`, '',
    `Corpus missing coverage: ${(report.missing_coverage || []).join(', ') || 'none'}.`, '',
    '## Flags', '', '| Check | Occurrences | Files |', '|---|---:|---:|'];
  for (const [name, data] of Object.entries(s.checks).sort((a, b) => b[1].count - a[1].count))
    lines.push(`| ${name} | ${data.count} | ${data.files} |`);
  if (!Object.keys(s.checks).length) lines.push('| None observed | 0 | 0 |');
  lines.push('', '## Most flagged files', '', '| Replay | Occurrences |', '|---|---:|');
  for (const row of s.worst_files) lines.push(`| ${row.path.replaceAll('|', '\\|')} | ${row.flags} |`);
  lines.push('', '## Dot fallbacks (internal cid / action state)', '', '| cid/state | Sampled draws |', '|---|---:|');
  for (const [key, count] of Object.entries(s.fallbacks).sort((a, b) => b[1] - a[1]).slice(0, 20)) lines.push(`| ${key} | ${count} |`);
  lines.push('', '## Interpretation', '',
    '- Counts are occurrences, not independent defects. Python rollback rows amplify paint counts.',
    '- Python producer is the original bundle, including rollback rows; fighter parity uses last-occurrence rows.',
    '- Python lacks item velocity. Laser angle checks still use independent raw-stream velocity.',
    '- Missing archives, parse errors, raw truncation and absent coverage are explicit flags, never silent passes.',
    '- Geometry is command-level only. No browser pixels, independent animation truth, Dolphin, R2 or mobile-host integration was checked.',
    '- Randall uses the host frame contract in the harness; mover calls are observed inside the real paintFrame.',
    '- See report.json / flags.jsonl for per-file examples with true frame and producer row.', '');
  return lines.join('\n');
}

async function main() {
  const options = args();
  if (options.help) { console.log(HELP); return; }
  const out = outDir(options.out), producer = options.producer || 'python';
  if (!['js', 'python'].includes(producer)) throw new Error('--producer must be js or python');
  const every = Number(options.every || 30);
  if (!Number.isInteger(every) || every < 1) throw new Error('--every must be a positive integer');
  const begin = performance.now(), shard = String(options.shard || '1/1');
  const python = options.python || path.join(ROOT, 'app/venv/Scripts/python.exe');
  const py = async (name, argv) => child(python, ['-B', path.join(ROOT, 'tools/liteaudit', name), ...argv]);
  const records = [], pipelineErrors = [];
  const sourceFiles = ['litePaint.js', 'meleeRender.js', 'meleeStages.js', 'liteStageInference.js',
    'liteDeriver/index.js', 'liteDeriver/deriveBundle.js', 'liteDeriver/slpParse.js', 'liteDeriver/constants.js', 'liteDeriver/window.js'];
  const hashSources = () => Object.fromEntries(sourceFiles.map(name => {
    try { return [name, createHash('sha256').update(fs.readFileSync(path.join(ROOT, 'app/frontend/src/tracker/replays', name))).digest('hex')]; }
    catch { return [name, null]; }
  }));
  const sourceHashes = hashSources();
  const reportName = `${producer}-${options.full ? 'full' : 'golden'}-${shard.replace('/', '-')}${options.limit ? `-limit${options.limit}` : ''}`;
  const runOut = path.join(out, 'reports', reportName);
  fs.mkdirSync(runOut, { recursive: true });
  try {
    if (!options['skip-corpus']) await py('corpus.py', ['--out', out,
      ...(options.root ? ['--root', options.root] : []), ...(options.size ? ['--size', options.size] : []),
      ...(options.refresh ? ['--refresh'] : [])]);
  } catch (error) { pipelineErrors.push(`corpus: ${error}`); }
  let manifest = {}, games = [];
  try { ({ manifest, games } = selection(options, out)); }
  catch (error) { pipelineErrors.push(`selection: ${error}`); }
  const shared = ['--out', out, '--manifest', options.manifest || path.join(out, options.full ? 'corpus.json' : 'golden.json'), '--shard', shard,
    ...(options.limit ? ['--limit', options.limit] : [])];
  try { await py('dump_truth.py', [...shared, ...(options.refresh ? ['--refresh'] : [])]); }
  catch (error) { pipelineErrors.push(`truth: ${error}`); }
  try { await py('extract_anims.py', [...shared, ...(options['anim-zips'] ? ['--anim-zips', options['anim-zips']] : [])]); }
  catch (error) { pipelineErrors.push(`animations: ${error}`); }
  let audited = 0;
  for (const [index, game] of games.entries()) {
    const record = { id: game.id, path: game.path, flags: {}, metrics: {} };
    try {
      const truth = readJSON(path.join(out, 'truth', `${game.id}.json.gz`));
      const { bundle, rowFids } = await produce(game, truth, producer, out);
      const data = checkData(bundle, rowFids, truth);
      Object.assign(record.flags, data.flags); Object.assign(record.metrics, data.metrics);
      if (producer === 'js' && truth.python_error) record.flags.js_only_playable = { count: 1, examples: [{ reason: truth.python_error }] };
      try {
        const render = checkRender(bundle, rowFids, truth, loadAnimations(bundle, out, shard), { every, traces: Number(options.traces || 0) });
        Object.assign(record.flags, render.flags); Object.assign(record.metrics, render.metrics);
        record.fallbacks = render.fallbacks;
        if (render.drawTraces.length) writeJSON(path.join(runOut, 'traces', `${game.id}.json`), render.drawTraces);
      } catch (error) { record.flags.render_error = { count: 1, examples: [{ error: String(error), stack: error.stack }] }; }
      audited++;
    } catch (error) { record.flags.producer_unavailable = { count: 1, examples: [{ error: String(error), stack: error.stack }] }; }
    records.push(record);
    if ((index + 1) % 10 === 0) console.log(`Audit ${index + 1}/${games.length} (${((performance.now() - begin) / 1000).toFixed(1)}s)`);
  }
  if (pipelineErrors.length) records.push({ id: 'pipeline', path: '', flags: {
    pipeline_error: { count: pipelineErrors.length, examples: pipelineErrors.map(error => ({ error })) } } });
  const sourceHashesAfter = hashSources();
  const changedSources = sourceFiles.filter(name => sourceHashes[name] !== sourceHashesAfter[name]);
  if (changedSources.length) records.push({ id: 'sources', path: '', flags: {
    sources_changed_during_run: { count: changedSources.length, examples: changedSources.map(file => ({ file })) } } });
  const report = { schema: 1, policy: 'highlight-only', producer, shard, every, selected: games.length,
    audited, unavailable: games.length - audited, seconds: +((performance.now() - begin) / 1000).toFixed(1),
    missing_coverage: manifest.missing_coverage || [], sourceHashes, sourceHashesAfter,
    summary: summary(records), records };
  const md = markdown(report);
  writeJSON(path.join(runOut, 'report.json'), report);
  fs.writeFileSync(path.join(runOut, 'report.md'), md);
  const jsonl = records.flatMap(r => Object.entries(r.flags).map(([check, details]) => JSON.stringify({ id: r.id, path: r.path, check, ...details }))).join('\n') + '\n';
  fs.writeFileSync(path.join(runOut, 'flags.jsonl'), jsonl);
  // Latest convenience copies may be last-writer-wins; durable reports are
  // namespaced by producer/corpus/shard so concurrent shards never lose results.
  writeJSON(path.join(out, 'report.json'), report);
  fs.writeFileSync(path.join(out, 'report.md'), md);
  console.log(md.split('## Most flagged files')[0]);
  console.log(`Detailed report: ${path.join(runOut, 'report.md')}`);
}

try { await main(); }
catch (error) {
  // Even setup failures are evidence for review, not a CI veto.
  console.error(`Audit setup unavailable (not a build gate): ${error.stack || error}`);
  const out = outDir();
  writeJSON(path.join(out, `setup-error-${process.pid}.json`), { policy: 'highlight-only', error: String(error), stack: error.stack });
}
