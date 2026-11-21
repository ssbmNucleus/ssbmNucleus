import test from 'node:test'
import assert from 'node:assert/strict'
import {registerDefaultStageSim,registerStageSim,simFor} from './index.js'

test('scoped overrides restore built-ins and still reject duplicate overrides',()=>{
  const id=98765,builtin=()=>({lines:[]}),override=()=>null
  registerDefaultStageSim(id,builtin)
  assert.equal(simFor(id),builtin)
  const dispose=registerStageSim(id,override)
  assert.equal(simFor(id),override)
  assert.throws(()=>registerStageSim(id,override),/already has/)
  dispose();assert.equal(simFor(id),builtin)
  dispose();assert.equal(simFor(id),builtin)
})
