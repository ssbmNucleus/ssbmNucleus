// Bundle entry.js (the real Watch Lite paint modules) into one browser script.
//   node build.mjs --out <paintlib.js> [--src <frontend src>]
// --src bundles another tree instead of this checkout's app/frontend/src, e.g. a
// git worktree of an older commit, to compare before and after.
import path from 'node:path'; import { createRequire } from 'node:module'; import { fileURLToPath } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const A = {}; const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i += 2) A[argv[i].replace(/^--/, '')] = argv[i + 1]
if (!A.out) { console.error('usage: node build.mjs --out <paintlib.js> [--src <frontend src>]'); process.exit(2) }
const require = createRequire(path.join(ROOT, 'app/frontend/package.json'))
const esbuild = require('esbuild')
const src = A.src ? path.resolve(A.src) : path.join(ROOT, 'app/frontend/src')
const R = path.join(src, 'tracker/replays')
await esbuild.build({
  entryPoints: [path.join(HERE, 'entry.js')], bundle: true, format: 'iife', outfile: A.out, logLevel: 'warning',
  define: { 'import.meta.env.DEV': 'false' },
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /^@R\// }, a => ({ path: path.join(R, a.path.slice(3)) }))
    b.onResolve({ filter: /shared\/config\/config/ }, () => ({ path: 'config', namespace: 'stub' }))
    b.onResolve({ filter: /shared\/transport\/api/ }, () => ({ path: 'api', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, a => ({ contents: a.path === 'config'
      ? 'export const BACKEND_URL = "offline:render"'
      : 'export const api = { get() { return Promise.reject(new Error("offline")) }, url: x => x }; export const authenticatedFetch = () => Promise.reject(new Error("offline"))', loader: 'js' }))
  } }],
})
console.log('built', A.out, 'from', src)
