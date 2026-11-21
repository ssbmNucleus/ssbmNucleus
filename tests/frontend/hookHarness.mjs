// Deterministic state/effect runner for the frontend's plain .js hooks. This
// exercises their production functions, not React rendering or DOM behavior.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../../app/frontend/package.json', import.meta.url))
const { transformSync } = require('esbuild')

export function loadModule(url, dependencies, globals = {}) {
  const { code } = transformSync(readFileSync(url, 'utf8'), { loader: 'js', format: 'cjs' })
  const module = { exports: {} }
  const resolve = name => {
    if (!(name in dependencies)) throw new Error(`Unstubbed dependency: ${name}`)
    return dependencies[name]
  }
  new Function('require', 'module', 'exports', ...Object.keys(globals), code)(
    resolve, module, module.exports, ...Object.values(globals))
  return module.exports
}

export const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
export const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }

export function hookHarness() {
  const slots = []
  let cursor = 0, effects = [], dirty = false
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((x, i) => !Object.is(x, b[i]))
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = { value: typeof initial === 'function' ? initial() : initial }
      const slot = slots[index]
      return [slot.value, update => {
        const value = typeof update === 'function' ? update(slot.value) : update
        if (!Object.is(slot.value, value)) { slot.value = value; dirty = true }
      }]
    },
    useRef(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = { current: initial }
      return slots[index]
    },
    useEffect(effect, deps) {
      const index = cursor++
      const slot = slots[index]
      if (!slot || changed(slot.deps, deps)) {
        slots[index] = { deps, cleanup: slot?.cleanup }
        effects.push(() => {
          slots[index].cleanup?.()
          slots[index].cleanup = effect()
        })
      }
    },
    useMemo(make, deps) {
      const index = cursor++
      if (!slots[index] || changed(slots[index].deps, deps)) slots[index] = { deps, value: make() }
      return slots[index].value
    },
    useCallback(callback, deps) { return react.useMemo(() => callback, deps) },
    useSyncExternalStore(subscribe, snapshot) {
      react.useEffect(() => subscribe(() => { dirty = true }), [subscribe])
      return snapshot()
    },
  }
  return {
    react,
    render(hook) {
      let value, renders = 0
      do {
        if (++renders > 50) throw new Error('Hook did not settle')
        dirty = false; cursor = 0
        value = hook()
        const pending = effects; effects = []
        pending.forEach(effect => effect())
      } while (dirty)
      return value
    },
    unmount() { for (const slot of slots) slot?.cleanup?.() },
  }
}
