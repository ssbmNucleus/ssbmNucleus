import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'

const src = fileURLToPath(new URL('../../', import.meta.url))
function styles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name)
    return entry.isDirectory() ? styles(file) : entry.name.endsWith('.css') ? [file] : []
  })
}

test('Tracker chart grid rules have one owner regardless of lazy stylesheet order', () => {
  const owners = new Set()
  for (const file of styles(src)) {
    postcss.parse(fs.readFileSync(file, 'utf8')).walkRules(rule => {
      if (/\.stats-grid(?![\w-])/.test(rule.selector)) owners.add(path.basename(file))
    })
  }
  // Settings' auto-fit 5rem tiles previously overwrote the chart columns.
  assert.deepEqual([...owners], ['StatsPage.css'])
})

test('storage statistics never reuse the Tracker chart grid class', () => {
  const source = fs.readFileSync(new URL('../../settings/StorageStatsSection.jsx', import.meta.url), 'utf8')
  const settings = postcss.parse(fs.readFileSync(new URL('../../settings/Settings.css', import.meta.url), 'utf8'))
  assert.doesNotMatch(source, /className="stats-grid"/)
  const gridClass = source.match(/className="([\w-]+-grid)"/)[1]
  const rules = []
  settings.walkRules(rule => { if (rule.selector === `.${gridClass}`) rules.push(rule) })
  assert.ok(rules.some(rule => rule.parent.type === 'root'), 'storage grid has its own base layout')
  assert.ok(rules.some(rule => rule.parent.name === 'media'), 'storage grid keeps its narrow layout')
})
