import test from 'node:test'
import assert from 'node:assert/strict'
import JSZip from 'jszip'
import { createPaintPair, addPaintPairToZip } from './paintPair.js'

const bytes = value => Buffer.from(value).toString('base64')
const pair = () => createPaintPair([
  { name: 'Popo', datName: 'PlPpRe.dat', datFile: '/tmp/PlPpRe.dat', datBase64: bytes('popo') },
  { name: 'Nana', datName: 'PlNnWh.dat', datFile: '/tmp/PlNnWh.dat', datBase64: bytes('nana') }
])

const painted = (members, index, datBase64) =>
  members.map((member, i) => i === index ? { ...member, datBase64 } : member)

test('saving after painting only Nana includes untouched Popo and edited Nana', async () => {
  const members = painted(pair(), 1, bytes('painted-nana'))
  const zip = new JSZip()
  addPaintPairToZip(zip, members)
  const saved = await JSZip.loadAsync(await zip.generateAsync({ type: 'nodebuffer' }))
  assert.deepEqual(Object.keys(saved.files), ['PlPpRe.dat', 'PlNnWh.dat'])
  assert.equal(await saved.file('PlPpRe.dat').async('string'), 'popo')
  assert.equal(await saved.file('PlNnWh.dat').async('string'), 'painted-nana')
})

test('saving Popo alone still preserves the original Nana', async () => {
  const members = painted(pair(), 0, bytes('painted-popo'))
  const zip = new JSZip()
  addPaintPairToZip(zip, members)
  assert.equal(await zip.file('PlNnWh.dat').async('string'), 'nana')
})

test('an incomplete pair is refused', () => {
  assert.throws(() => createPaintPair(pair().slice(0, 1)), /complete Popo\/Nana/)
})
