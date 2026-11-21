const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const React = require('react')
const { transformSync } = require('esbuild')

function editor() {
  const slots = []; let index = 0; let effects = []; const requests = []
  const context = vm.createContext({ React,
    useState: initial => {
      const slot = index++
      if (!(slot in slots)) slots[slot] = initial
      return [slots[slot], value => { slots[slot] = value }]
    },
    useEffect: effect => { effects.push(effect) },
    createPortal: value => value,
    getAppContentPortalTarget: () => null,
    VisualEffectEditor: 'color-workspace', ColorRow: 'color-row', PresetRow: 'presets',
    CloseIcon: () => null, SaveIcon: () => null,
    readEditorColors: (mod, defaults) => defaults,
    rgbWithAlpha: value => value,
    playSound: () => {}, appConfirm: async () => true,
    api: { post: async (url, body) => { requests.push({ url, body }); return { mod: body } } },
  })
  const source = fs.readFileSync(path.join(__dirname, 'SideBEditorModal.jsx'), 'utf8')
    .replace(/^import .*$/gm, '').replace('export default ', '')
  vm.runInContext(transformSync(source, { loader: 'jsx' }).code, context)
  vm.runInContext('this.Component=SideBEditorModal', context)
  return {
    requests,
    render(props) {
      index = 0; effects = []
      context.Component(props)
      effects.forEach(effect => effect())
      index = 0; effects = []
      return context.Component(props)
    },
  }
}
function nodes(element) {
  if (!element || typeof element !== 'object') return []
  return [element, ...React.Children.toArray(element.props?.children).flatMap(nodes)]
}
const base = { show: true, character: 'Falco', extraType: { id: 'sideb', properties: [] } }

test('imported afterimage editor preserves its model recipe when renamed and hides color controls', async () => {
  const harness = editor()
  const recipe = { sideb_model: { version: 1, sha256: 'source-mesh' } }
  const tree = harness.render({ ...base, editingMod: { id: 'spooky', name: 'Spooky', modifications: recipe } })
  assert.equal(nodes(tree).some(node => node.type === 'color-workspace'), false)
  assert.ok(nodes(tree).some(node => node.type === 'p'))
  const save = nodes(tree).find(node => node.props?.className === 'laser-editor-save')
  await save.props.onClick()
  assert.equal(harness.requests.length, 1)
  assert.equal(harness.requests[0].body.modifications, recipe)
  assert.equal(harness.requests[0].body.modId, 'spooky')
})

test('ordinary Side-B color mods keep the color editor', () => {
  const tree = editor().render({ ...base, editingMod: { id: 'blue', name: 'Blue', modifications: { primary: { color: '0099FFFF' } } } })
  assert.ok(nodes(tree).some(node => node.type === 'color-workspace'))
})
