const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { transformSync } = require('esbuild')

const frontend = path.resolve(__dirname, '../../..')
const context = vm.createContext({
  useState: value => [value, () => {}],
  useCallback: fn => fn,
  useMemo: fn => fn(),
})
for (const relative of ['shared/data/extraTypes.js', 'vault/lib/relativeRecolor.js',
  'vault/extras/pictograms.js', 'vault/extras/EditorControls.jsx']) {
  const source = fs.readFileSync(path.join(frontend, 'src', relative), 'utf8')
    .replace(/^import .*$/gm, '').replaceAll('export default ', '').replaceAll('export ', '')
  vm.runInContext(transformSync(source, { loader: relative.endsWith('.jsx') ? 'jsx' : 'js' }).code, context)
}
const api = vm.runInContext('({ EXTRA_TYPES, deriveLayerGroups })', context)
const plain = value => JSON.parse(JSON.stringify(value))

test('Screw Attack exposes independent arc and warm swirl channels in Advanced', () => {
  const config = api.EXTRA_TYPES.Samus.find(extra => extra.id === 'screw_attack')
  const groups = plain(api.deriveLayerGroups(config))
  assert.deepEqual(groups.find(group => group.label === 'Arc').controls.map(control => control.keys),
    [['arc_c1'], ['arc_c2']])
  assert.deepEqual(groups.find(group => group.label === 'Warm Swirl').controls.map(control => control.keys),
    [['warm_swirl_c1'], ['warm_swirl_c2']])
  const main = groups.find(group => group.id === '__main')
  assert.deepEqual(main.controls.map(control => control.keys),
    [['color1', 'arc_c1', 'warm_swirl_c1'], ['color2', 'arc_c2', 'warm_swirl_c2']])
  // Reproduce the real ColorRow callback: the summary must change native
  // values already initialized to vanilla, not only preview summaries.
  const current = { ...config.vanilla }
  main.controls[0].keys.forEach(key => { current[key] = '00FF00' })
  assert.equal(current.warm_swirl_c1, '00FF00')
  assert.equal(current.arc_c1, '00FF00')
  assert.equal(current.warm_swirl_c2, 'FF4C00')
})

test('element guides take precedence over overview crops without inventing Core/Tint anatomy', () => {
  for (const [owner, id, labels] of [
    ['Samus', 'screw_attack', ['Arc', 'Warm Swirl']],
    ['Fox', 'charge_flames', ['Flame', 'Wisp']],
  ]) {
    const config = api.EXTRA_TYPES[owner].find(extra => extra.id === id)
    const groups = api.deriveLayerGroups(config)
    for (const label of labels) {
      const group = groups.find(item => item.label === label)
      assert.ok(group?.picto?.endsWith('.svg'), `${owner}/${id}/${label} guide missing`)
      assert.ok(fs.existsSync(path.join(frontend, 'public', group.picto)))
      assert.ok(group.controls.every(control => control.picto === null))
    }
  }
})

test('every offset-backed summary row has a native write target and fans to matching channels', () => {
  for (const extras of Object.values(api.EXTRA_TYPES)) for (const config of extras) {
    const native = Object.keys(config.offsets || {})
    if (!native.length) continue
    const main = api.deriveLayerGroups(config).find(group => group.id === '__main')
    for (const control of main?.controls || []) {
      assert.ok(control.keys.some(key => native.includes(key)), `${config.id}/${control.id} has no native target`)
      const suffix = control.keys.includes('color1') ? /_(c1|core)$/
        : control.keys.includes('color2') ? /_(c2|glow)$/ : null
      if (suffix) for (const key of native.filter(key => suffix.test(key))) {
        assert.ok(control.keys.includes(key), `${config.id}/${control.id} omits ${key}`)
      }
    }
  }
})

test('orphan summaries disappear while real single-texture property controls remain', () => {
  const groups = api.deriveLayerGroups({ id: 'example', offsets: { body: { size: 3, format: 'RGB' } },
    properties: [{ id: 'color1', name: 'Primary' }, { id: 'color2', name: 'Secondary' }] })
  assert.ok(!groups.some(group => group.id === '__main'))
  const texture = api.deriveLayerGroups({ id: 'texture', properties: [{ id: 'color1', name: 'Texture' }] })
  assert.deepEqual(plain(texture[0].controls[0].keys), ['color1'])
})
