import test from 'node:test'
import assert from 'node:assert/strict'
import { extractPalette, rgbToHex } from './colorUtils.js'

// A stand-in for ImageData: extractPalette only reads .data.
const image = (pixels) => ({ data: Uint8ClampedArray.from(pixels.flat()) })
const opaque = (r, g, b) => [r, g, b, 255]

test('extractPalette finds the colors an image is actually made of', () => {
  const pixels = []
  for (let i = 0; i < 100; i++) pixels.push(opaque(255, 0, 0))
  for (let i = 0; i < 100; i++) pixels.push(opaque(0, 0, 255))
  const palette = extractPalette(image(pixels), 2)
  assert.equal(palette.length, 2)
  assert.deepEqual(palette.map(entry => entry.color).sort(), ['#0000ff', '#ff0000'])
})

test('the palette is ordered by how much of the image each color covers', () => {
  const pixels = []
  for (let i = 0; i < 20; i++) pixels.push(opaque(0, 255, 0))
  for (let i = 0; i < 200; i++) pixels.push(opaque(0, 0, 0))
  const palette = extractPalette(image(pixels), 2)
  assert.equal(palette[0].color, '#000000')
  assert.ok(palette[0].weight > palette[1].weight)
})

test('transparent pixels carry no color and are skipped', () => {
  const pixels = []
  for (let i = 0; i < 50; i++) pixels.push([255, 255, 255, 0])   // fully transparent
  for (let i = 0; i < 50; i++) pixels.push(opaque(18, 52, 86))
  const palette = extractPalette(image(pixels), 4)
  assert.deepEqual(palette.map(entry => entry.color), ['#123456'])
})

test('a fully transparent image yields no palette rather than throwing', () => {
  const pixels = Array.from({ length: 40 }, () => [1, 2, 3, 0])
  assert.deepEqual(extractPalette(image(pixels), 5), [])
})

test('asking for more colors than exist does not invent any', () => {
  const pixels = Array.from({ length: 60 }, () => opaque(10, 20, 30))
  const palette = extractPalette(image(pixels), 8)
  assert.deepEqual(palette.map(entry => entry.color), ['#0a141e'])
})

test('rgbToHex clamps out-of-range channels', () => {
  assert.equal(rgbToHex(300, -5, 128), '#ff0080')
})
