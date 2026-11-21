import test from 'node:test'
import assert from 'node:assert/strict'
import { createCardActivation } from './cardActivation.js'

const down = { button: 0, clientX: 20, clientY: 20 }

test('a normal click, including small pointer jitter, opens once', () => {
  const card = createCardActivation()
  let opens = 0
  card.onPointerDown(down)
  card.onPointerMove({ clientX: 22, clientY: 23 })
  card.onClick({ button: 0 }, () => opens++)
  assert.equal(opens, 1)
})

test('pointer movement suppresses edit and a new deliberate click works', () => {
  const card = createCardActivation()
  let opens = 0
  card.onPointerDown(down)
  card.onPointerMove({ clientX: 35, clientY: 20 })
  card.onClick({ button: 0 }, () => opens++)
  assert.equal(opens, 0)
  card.onPointerDown(down)
  card.onClick({ button: 0 }, () => opens++)
  assert.equal(opens, 1)
})

test('native drag start suppresses its trailing click without pointer events', () => {
  const card = createCardActivation()
  card.onDragStart()
  card.onClick({ button: 0 }, () => assert.fail('drag must not open editor'))
})

test('shared drag completion guard blocks a click on a drop target', () => {
  const justDragged = { current: true }
  const target = createCardActivation(justDragged)
  target.onClick({ button: 0 }, () => assert.fail('drop must not open target'))
  justDragged.current = false
  let opens = 0
  target.onPointerDown(down)
  target.onClick({ button: 0 }, () => opens++)
  assert.equal(opens, 1)
})

test('pointer cancellation cannot accidentally open the card', () => {
  const card = createCardActivation()
  card.onPointerDown(down)
  card.onPointerCancel()
  card.onClick({ button: 0 }, () => assert.fail('cancelled gesture'))
})

test('Enter and Space activate the focused card, without repeating or hijacking children', () => {
  const card = createCardActivation()
  const target = {}
  let opens = 0, prevented = 0
  const event = { target, currentTarget: target, preventDefault: () => prevented++ }
  for (const key of ['Enter', ' ']) card.onKeyDown({ ...event, key }, () => opens++)
  card.onKeyDown({ ...event, key: 'Enter', repeat: true }, () => opens++)
  card.onKeyDown({ ...event, key: 'Enter', target: {} }, () => opens++)
  card.onKeyDown({ ...event, key: 'Escape' }, () => opens++)
  assert.equal(opens, 2)
  assert.equal(prevented, 2)
})

test('secondary-button clicks retain their context-menu behavior', () => {
  createCardActivation().onClick({ button: 2 }, () => assert.fail('secondary click'))
})
