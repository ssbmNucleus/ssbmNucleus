import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

// Run the hook's state transitions with deterministic effects and an in-memory canvas.
// No DOM, native viewer, filesystem fixtures or app startup is required.
test('undo histories follow DAT owner and reject canvas loading or saving races', async () => {
  const states = [], effects = []
  let cursor = 0, queued = [], value = 'popo-original', editable = true, updates = 0
  globalThis.__paintUndoHooks = {
    useState(initial) {
      const slot = cursor++
      if (!(slot in states)) states[slot] = initial
      return [states[slot], update => { states[slot] = typeof update === 'function' ? update(states[slot]) : update }]
    },
    useEffect(callback, dependencies) {
      const slot = cursor++
      if (!effects[slot] || dependencies.some((dep, i) => dep !== effects[slot][i])) queued.push(callback)
      effects[slot] = dependencies
    }
  }
  const previousWindow = globalThis.window
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  try {
    const source = (await readFile(new URL('./useUndoRedo.js', import.meta.url), 'utf8'))
      .replace("import { useState, useEffect } from 'react'", 'const { useState, useEffect } = globalThis.__paintUndoHooks')
    const { useUndoRedo } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
    const context = { getImageData: () => value, putImageData: state => { value = state } }
    const options = { paintCanvasRef: { current: { width: 1, height: 1, getContext: () => context } },
      sendTextureUpdate: () => updates++, selectedTextureIndex: 'popo:0', resetKey: 'session',
      isOpen: true, skinCreatorStep: 'edit', canEdit: () => editable }
    const render = () => {
      cursor = 0
      const hook = useUndoRedo(options)
      const pending = queued; queued = []; pending.forEach(effect => effect())
      return hook
    }
    render()
    let hook = render()
    hook.saveToUndoStack()
    value = 'popo-painted'
    options.selectedTextureIndex = 'nana:0'
    value = 'nana-original'
    hook = render()
    assert.equal(hook.undoStack.length, 0)
    hook.saveToUndoStack()
    value = 'nana-painted'
    options.selectedTextureIndex = 'popo:0'
    value = 'popo-painted'
    hook = render()
    hook.undo()
    assert.equal(value, 'popo-original')
    hook = render()
    hook.redo()
    assert.equal(value, 'popo-painted')
    options.selectedTextureIndex = 'nana:0'
    editable = false // Partner selected; canvas is still displaying Popo.
    hook = render()
    const before = updates
    hook.undo(); hook.redo(); hook.saveToUndoStack()
    assert.equal(value, 'popo-painted')
    assert.equal(updates, before)
    editable = true
    value = 'nana-painted'
    hook = render()
    hook.undo()
    assert.equal(value, 'nana-original')
    options.isOpen = false // Saving/loading disables history actions as well as buttons.
    hook = render()
    hook.redo()
    assert.equal(value, 'nana-original')
  } finally {
    globalThis.window = previousWindow
    delete globalThis.__paintUndoHooks
  }
})
