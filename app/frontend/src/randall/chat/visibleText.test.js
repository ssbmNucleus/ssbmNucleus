import test from 'node:test'
import assert from 'node:assert/strict'
import { visibleAssistantText } from './visibleText.js'

test('reasoning envelopes and orphan model tags never appear in the bubble', () => {
  assert.equal(visibleAssistantText('</mm:think>Hello 👋'), 'Hello 👋')
  assert.equal(visibleAssistantText('<think>private reasoning</think>**Hello** 🌤️'), '**Hello** 🌤️')
  assert.equal(visibleAssistantText('<mm:think>unfinished reasoning'), '')
})
test('streaming tag fragments stay hidden; emoji and normal Markdown survive', () => {
  for (const tag of ['<mm:think>', '</mm:think>', '<think>', '</think>']) {
    for (let i = 1; i < tag.length; i++) assert.equal(visibleAssistantText(tag.slice(0, i)), '', tag.slice(0, i))
  }
  assert.equal(visibleAssistantText('👨‍👩‍👧‍👦 **Nice!** 🎨 [[clip:example|Watch]]'), '👨‍👩‍👧‍👦 **Nice!** 🎨 [[clip:example|Watch]]')
  assert.equal(visibleAssistantText('x < y; use <img>'), 'x < y; use <img>')
})
