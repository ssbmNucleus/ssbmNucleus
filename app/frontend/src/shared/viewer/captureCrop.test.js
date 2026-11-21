import { test } from 'node:test'
import assert from 'node:assert/strict'
import { captureCrop } from './captureCrop.js'

test('a 4:3 client under a title bar fills the stage and leaves the bar above it', () => {
  // 640x480 game, 1px side borders, 31px title bar, 1px bottom border.
  const style = captureCrop({ x: 1, y: 31, width: 640, height: 480, frameWidth: 642, frameHeight: 512 })
  assert.equal(style.width, '100.31%')
  assert.equal(style.height, '106.67%')
  assert.equal(style.left, '-0.16%')
  assert.equal(style.top, '-6.46%')
  assert.equal(style.objectFit, 'fill')
})

test('a taller client is letterboxed by Dolphin: the stage takes its centred 4:3 picture', () => {
  // 640x528 client (Melee's EFB height), no borders: 24px bars above and below the picture.
  const style = captureCrop({ x: 0, y: 30, width: 640, height: 528, frameWidth: 640, frameHeight: 558 })
  assert.equal(style.width, '100%')
  assert.equal(style.top, `${Math.round(-(30 + 24) / 480 * 10000) / 100}%`)
  assert.equal(style.height, `${Math.round(558 / 480 * 10000) / 100}%`)
})

test('a wider client crops its side bars instead', () => {
  const style = captureCrop({ x: 0, y: 0, width: 800, height: 480, frameWidth: 800, frameHeight: 480 })
  assert.equal(style.left, '-12.5%')
  assert.equal(style.width, '125%')
  assert.equal(style.height, '100%')
})

test('unknown or impossible geometry falls back to the whole frame', () => {
  assert.equal(captureCrop(null), null)
  assert.equal(captureCrop({ x: 0, y: 0, width: 0, height: 480, frameWidth: 640, frameHeight: 480 }), null)
  assert.equal(captureCrop({ x: 10, y: 0, width: 640, height: 480, frameWidth: 640, frameHeight: 480 }), null)
  assert.equal(captureCrop({ x: 0, y: 0, width: 640, height: 480 }), null)
})
