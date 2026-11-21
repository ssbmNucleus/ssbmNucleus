import test from 'node:test'
import assert from 'node:assert/strict'
import { DOWN, next } from './importDrag.js'

const run = (events, depth = DOWN) => events.reduce(next, depth)
const enter = (extra = {}) => ({ type: 'dragenter', files: true, onScreen: true, ...extra })
const leave = { type: 'dragleave' }

test('a file dragged over the vault raises the screen, and leaving lowers it', () => {
  assert.equal(run([enter()]), 1)
  assert.equal(run([enter(), leave]), DOWN)
})

test('crossing onto a child element keeps it up', () => {
  assert.equal(run([enter(), enter(), leave]), 1)
  assert.equal(run([enter(), enter(), leave, leave]), DOWN)
})

test('a vault that another page covers raises nothing', () => {
  // A model dropped on a chat: the vault is mounted behind the AI page.
  assert.equal(run([enter({ onScreen: false }), enter({ onScreen: false })]), DOWN)
})

test('a drag that carries no file raises nothing', () => {
  assert.equal(run([enter({ files: false })]), DOWN)
})

test('the end of the drag lowers it however deep the drag was', () => {
  // The drop is heard before a chat's handler can stop it.
  assert.equal(run([enter(), enter(), { type: 'drop' }]), DOWN)
  assert.equal(run([enter(), enter(), { type: 'dragend' }]), DOWN)
})

test('a stray leave never goes below down', () => {
  assert.equal(run([leave, leave, enter()]), 1)
})
