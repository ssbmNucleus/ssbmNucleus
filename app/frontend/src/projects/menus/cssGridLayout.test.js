import test from 'node:test'
import assert from 'node:assert/strict'
import { applyCssTemplate, computeAutoCssLayout, gridIcons, pickAutoColumns } from './cssGridLayout.js'

const TEMPLATE = { iconSideDropX: 0, iconSideDropY: 0, iconSideDropZ: 0 }

const makeIcons = (n) => Array.from({ length: n }, (_, i) => ({
  fighter: i, x: 100 + i, y: 100, z: 0, scaleX: 1, scaleY: 1,
  collisionSizeX: 7.05, collisionSizeY: 7.2, collisionOffsetX: 0, collisionOffsetY: 0
}))

test('auto layout with no alternates matches the plain layout', () => {
  const icons = makeIcons(28)
  assert.deepEqual(computeAutoCssLayout(icons, TEMPLATE, []), computeAutoCssLayout(icons, TEMPLATE))
  assert.equal(computeAutoCssLayout(icons, TEMPLATE).template.iconsPerRow, pickAutoColumns(28))
})

test('tucked alternates take no grid slot and stay untouched in place', () => {
  // 30 icons, 3 of them alternates: the grid is fitted to 27 (vanilla 9x3)
  const icons = makeIcons(30)
  const alts = [4, 12, 29]
  const { icons: out, template } = computeAutoCssLayout(icons, TEMPLATE, alts)

  assert.equal(template.iconsPerRow, 9)
  assert.equal(out.length, 30)
  alts.forEach(f => assert.equal(out[f], icons[f]))

  // The visible icons fill the 27 slots exactly as a 27-icon roster would
  const visibleOnly = computeAutoCssLayout(gridIcons(icons, alts), TEMPLATE)
  assert.deepEqual(gridIcons(out, alts), visibleOnly.icons)
})

test('manual template apply skips tucked icons too', () => {
  const icons = makeIcons(10)
  const template = computeAutoCssLayout(makeIcons(9), TEMPLATE).template
  const out = applyCssTemplate(icons, template, [0])
  assert.equal(out[0], icons[0])
  assert.deepEqual(out.slice(1), applyCssTemplate(icons.slice(1), template))
})
