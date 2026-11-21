import test from 'node:test'
import assert from 'node:assert/strict'
import { poseChoices, showingPose } from './posePickerModel.js'

const poses = [{ name: 'eyes', thumbnailUrl: '/storage/poses/Yoshi/eyes_thumb.png' }, { name: 'jump', thumbnailUrl: null }]
const alts = [
  { id: 'e_hd', poseName: 'eyes', isHd: true },
  { id: 'e', poseName: 'eyes', isHd: false },
  { id: 'up', poseName: null, isHd: false },
]

test('the default pose comes first and asks for no pose by name', () => {
  const [first, ...rest] = poseChoices(poses, { alternateCsps: [] })
  assert.equal(first.pose, null)
  assert.deepEqual(rest.map(choice => choice.pose), ['eyes', 'jump'])
})

test('a costume on its original portrait shows the default pose', () => {
  assert.equal(showingPose({ active_csp_id: null, alternateCsps: alts }), null)
  assert.deepEqual(poseChoices(poses, { alternateCsps: alts }).filter(c => c.showing).map(c => c.label),
    ['Default pose'])
})

test('a costume showing a pose marks that pose, not the default', () => {
  const costume = { active_csp_id: 'e', alternateCsps: alts }
  assert.equal(showingPose(costume), 'eyes')
  assert.deepEqual(poseChoices(poses, costume).filter(c => c.showing).map(c => c.pose), ['eyes'])
})

test('an uploaded picture that is showing is no pose: nothing is marked', () => {
  const costume = { active_csp_id: 'up', alternateCsps: alts }
  assert.equal(poseChoices(poses, costume).some(c => c.showing), false)
})

test('the pose menu\'s own default-pose render counts as the default', () => {
  const costume = { active_csp_id: 'd', alternateCsps: [{ id: 'd', poseName: 'Default pose', isHd: false }] }
  assert.deepEqual(poseChoices(poses, costume).filter(c => c.showing).map(c => c.pose), [null])
})

test('a character with no saved poses still offers the default', () => {
  assert.deepEqual(poseChoices([], {}).map(c => c.label), ['Default pose'])
})
