import test from 'node:test'
import assert from 'node:assert/strict'
import { getProjectGeneration, setProjectGeneration, isProjectChanged } from './projectGeneration.js'

test('generation starts unknown, accepts zero, and ignores absent status fields', () => {
  assert.equal(getProjectGeneration(), null)
  setProjectGeneration(0)
  assert.equal(getProjectGeneration(), 0)
  setProjectGeneration(7)
  setProjectGeneration(undefined)
  setProjectGeneration(null)
  assert.equal(getProjectGeneration(), 7)
})

test('only a project_changed conflict drops project-bound work', () => {
  assert.equal(isProjectChanged({ status: 409, data: { code: 'project_changed' } }), true)
  for (const error of [null, {}, { status: 409 }, { status: 409, data: { code: 'busy' } },
    { status: 500, data: { code: 'project_changed' } }]) assert.equal(isProjectChanged(error), false)
})
