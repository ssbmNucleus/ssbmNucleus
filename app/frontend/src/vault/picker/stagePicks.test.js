// What the stage picker offers and what a stage pick is, from the two backend
// lists it reads: status.recolor_stages and the Vault's stage variant list.
import assert from 'node:assert/strict'
import test from 'node:test'
import { stageOptions, stagePickLabel, stagePickValue, stageRows, stockStage, variantCounts, variantOptions, vaultStageVariants } from './stagePicks.js'

const STAGES = [
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', legal: true, art: '/vanilla/stages/battlefield.png' },
  { code: 'GrCn', name: 'Corneria', folder: 'corneria', legal: false, art: '/api/mex/stages/GrCn/art/icon' },
]
// GET /api/mex/das/storage/variants rows (vault/routes/das.py), a folder row among them.
const VARIANTS = [
  { type: 'folder', stageCode: 'GrNBa', id: 'folder_1', name: 'Night ones' },
  { stageCode: 'GrNBa', id: 'night-sky-1a2b', name: 'Night Sky', hasScreenshot: true,
    screenshotUrl: '/storage/das/battlefield/night-sky-1a2b_screenshot.png' },
  { stageCode: 'GrNBa', id: 'plain', name: 'plain', hasScreenshot: false, screenshotUrl: null },
  { stageCode: 'GrPs', id: 'fire', name: 'Fire', hasScreenshot: false },
]

test('stage rows keep the backend order and drop malformed ones', () => {
  assert.deepEqual(stageRows([...STAGES, null, { code: 'GrX' }, { name: 'nameless' }]), STAGES)
  assert.deepEqual(stageRows(undefined), [])
})

test('one stage’s vault variants are picks with their screenshots; folders are not picks', () => {
  assert.deepEqual(vaultStageVariants(VARIANTS, STAGES[0]), [
    { kind: 'stage', stage: 'GrNBa', stageName: 'Battlefield', id: 'night-sky-1a2b', name: 'Night Sky',
      image: '/storage/das/battlefield/night-sky-1a2b_screenshot.png' },
    { kind: 'stage', stage: 'GrNBa', stageName: 'Battlefield', id: 'plain', name: 'plain', image: null },
  ])
  assert.deepEqual(vaultStageVariants(VARIANTS, STAGES[1]), [])
  assert.deepEqual(variantCounts(VARIANTS), { GrNBa: 2, GrPs: 1 })
})

test('the stock stage is a pick pictured by its stage art', () => {
  assert.deepEqual(stockStage(STAGES[1]), { kind: 'stage', stage: 'GrCn', stageName: 'Corneria', vanilla: true,
    name: 'Corneria', image: '/api/mex/stages/GrCn/art/icon' })
  assert.equal(stockStage(null), null)
})

test('values and labels tell a variant from the stock stage', () => {
  const [night] = vaultStageVariants(VARIANTS, STAGES[0])
  assert.equal(stagePickValue(night), 'v:night-sky-1a2b')
  assert.equal(stagePickValue(stockStage(STAGES[0])), 's:GrNBa')
  assert.equal(stagePickValue({ kind: 'vault', id: 'x' }), '')
  assert.equal(stagePickLabel(night), 'Battlefield · Night Sky')
  assert.equal(stagePickLabel(stockStage(STAGES[0])), 'Battlefield (stock)')
  assert.equal(stagePickLabel(null), '')
})

test('grid options: stages badged with their variant count, then a stage’s variants and the stock one', () => {
  const url = path => `http://backend${path}`
  assert.deepEqual(stageOptions(STAGES, VARIANTS, url), [
    { value: 'GrNBa', label: 'Battlefield', icon: 'http://backend/vanilla/stages/battlefield.png', badge: '2' },
    { value: 'GrCn', label: 'Corneria', icon: 'http://backend/api/mex/stages/GrCn/art/icon' },
  ])
  const vault = vaultStageVariants(VARIANTS, STAGES[0])
  assert.deepEqual(variantOptions(vault, stockStage(STAGES[0]), url), [
    { value: 'v:night-sky-1a2b', label: 'Night Sky', icon: 'http://backend/storage/das/battlefield/night-sky-1a2b_screenshot.png' },
    { value: 'v:plain', label: 'plain', icon: undefined },
    { value: 's:GrNBa', label: 'Battlefield', icon: 'http://backend/vanilla/stages/battlefield.png', badge: 'Stock' },
  ])
})
