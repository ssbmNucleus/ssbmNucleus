const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const React = require('react')
const { transformSync } = require('esbuild')
const { effectReference, EFFECT_REFERENCES } = require('./effectReferences.js')
const { UPB_CONTROL_SECTIONS } = require('./upbParts.js')

function editor() {
  const slots = []; let index = 0
  const context = vm.createContext({ React, effectReference,
    useState: initial => {
      const slot = index++
      if (!(slot in slots)) slots[slot] = initial
      return [slots[slot], value => { slots[slot] = value }]
    },
    useId: () => 'visual-test',
  })
  for (const filename of ['LiveEffectPictogram.jsx', 'VisualEffectEditor.jsx']) {
    const source = fs.readFileSync(path.join(__dirname, filename), 'utf8')
      .replace(/^import .*$/gm, '').replaceAll('export default ', '').replaceAll('export ', '')
    vm.runInContext(transformSync(source, { loader: 'jsx' }).code, context)
  }
  vm.runInContext('this.Component=VisualEffectEditor', context)
  return props => { index = 0; return context.Component(props) }
}
function nodes(element) {
  if (!element || typeof element !== 'object') return []
  return [element, ...(typeof element.type === 'function' ? nodes(element.type(element.props)) : React.Children.toArray(element.props?.children).flatMap(nodes))]
}
const parts = UPB_CONTROL_SECTIONS.flatMap(section => section.parts)
const controls = part => React.createElement('output', { 'data-controls': part.controls.map(control => control.key).join(',') })
const selection = tree => nodes(tree).find(node => node.type === 'output').props['data-controls']

test('Up-B workspace focus opens just that part; pictogram shapes switch its real control set', () => {
  const render = editor()
  const props = { effectId: 'upb', character: 'Fox', parts, initialPart: 'flight_puffs', renderControls: controls }
  let tree = render(props)
  assert.equal(selection(tree), 'trail,small_trail')
  const pin = nodes(tree).find(node => node.type === 'g' && node.props['aria-label'] === 'Edit Main Flame')
  pin.props.onClick()
  tree = render(props)
  assert.equal(selection(tree), 'tip,body,fire')
  assert.equal(nodes(tree).find(node => node.props?.['data-highlight'])?.props['data-highlight'], 'main_flame')
  assert.equal(nodes(tree).filter(node => node.type === 'g' && node.props['aria-pressed']).length, 1)
  const startup = nodes(tree).find(node => node.type === 'select')
  startup.props.onChange({ target: { value: 'startup' } })
  assert.equal(selection(render(props)), 'rings,charge_lines')
  assert.equal(nodes(render(props)).find(node => node.props?.['data-highlight'])?.props['data-highlight'], 'startup')
})

test('pictogram selection supports keyboard activation and safely falls back from a stale part', () => {
  const render = editor()
  const props = { effectId: 'upb', character: 'Falco', parts, initialPart: 'removed-part', renderControls: controls }
  assert.equal(selection(render(props)), 'rings,charge_lines')
  const flight = nodes(render(props)).find(node => node.type === 'select')
  flight.props.onChange({ target: { value: 'main_flame' } })
  const pin = nodes(render(props)).find(node => node.type === 'g' && node.props['aria-label'] === 'Edit Fire Puffs')
  let prevented = false
  pin.props.onKeyDown({ key: ' ', preventDefault: () => { prevented = true } })
  assert.ok(prevented)
  assert.equal(selection(render(props)), 'trail,small_trail')
})

const publicDir = path.resolve(__dirname, '../../../public')
// The in-game screenshots the references crop; the public source drop leaves them out.
const referencesDir = path.join(publicDir, 'extras', 'references')

test('every curated reference ships an image', {
  skip: !fs.existsSync(referencesDir) &&
    'needs app/frontend/public/extras/references, which the public source drop leaves out (in-game screenshots)',
}, () => {
  for (const references of Object.values(EFFECT_REFERENCES)) for (const ref of Object.values(references)) {
    assert.ok(fs.existsSync(path.join(publicDir, ref.src)), ref.src)
  }
})

test('every curated reference keeps its hotspots inside the cropped viewport', () => {
  for (const references of Object.values(EFFECT_REFERENCES)) for (const ref of Object.values(references)) {
    const [x, y, w, h] = ref.viewBox.split(' ').map(Number)
    assert.ok(w > 0 && h > 0)
    if (ref.point) assert.ok(ref.point[0] >= x && ref.point[0] <= x + w && ref.point[1] >= y && ref.point[1] <= y + h, ref.src)
  }
})

test('overview fallback stays honest and does not invent a selectable layer location', () => {
  const ref = effectReference('falcon_kick', { id: 'Trail', controls: [{ keys: ['trail_c1', 'trail_c2'] }] })
  assert.match(ref.src, /trail_c1\.png$/)
  assert.equal(ref.point, undefined)
  assert.equal(ref.outline, undefined)
  assert.equal(effectReference('unknown', { id: 'unknown' }), null)
})

test('current colors repaint the composed SVG while the game image remains a reference', () => {
  const render = editor()
  const props = { effectId: 'upb', character: 'Fox', parts, initialPart: 'main_flame', renderControls: controls,
    previewColors: { tip: '#FFAA00', body: 'FFFFFF', fire: 'FF3300', trail: '224488', small_trail: '66CCFF', dots: 'FF66CC', flare: 'FFFFFF' } }
  const tree = render(props)
  const reference = nodes(tree).find(node => node.type === 'image').props.href
  assert.ok(nodes(tree).some(node => node.type === 'path' && node.props.fill === '#FF3300'))
  const changed = render({ ...props, previewColors: { ...props.previewColors, fire: '00CCFF' } })
  assert.ok(nodes(changed).some(node => node.type === 'path' && node.props.fill === '#00CCFF'))
  assert.ok(!nodes(changed).some(node => node.type === 'path' && node.props.fill === '#FF3300'))
  assert.equal(nodes(changed).find(node => node.type === 'image').props.href, reference)
  assert.equal(selection(changed), 'tip,body,fire')
})
