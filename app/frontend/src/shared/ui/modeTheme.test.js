import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import postcss from 'postcss'

// The mode themes: <html data-mode> re-points index.css's colour tokens, green
// for Tracker (internal id 'nucleome') and purple for Play, and the wordmark
// (BrandWordmark.css) takes each mode's accent. Play's purple is a gated
// preview look: it must cover what Tracker's green covers, read at least as
// well, and touch nothing in Nucleus or Tracker.

const sheet = (file) => postcss.parse(readFileSync(new URL(file, import.meta.url), 'utf8'))
const INDEX = sheet('../../index.css')
const APP = sheet('../../App.css')
const WORDMARK = sheet('./BrandWordmark.css')

function customProps(root, selector) {
  const props = {}
  root.walkRules((rule) => {
    if (rule.selector === selector) rule.walkDecls(/^--/, (decl) => { props[decl.prop] = decl.value })
  })
  return props
}

function declValue(root, selector, prop) {
  let value = null
  root.walkRules((rule) => {
    if (rule.selectors.includes(selector)) rule.walkDecls(prop, (decl) => { value = decl.value })
  })
  return value
}

const ROOT = customProps(INDEX, ':root')
const TRACKER_BLOCK = customProps(INDEX, '[data-mode="nucleome"]')
const PLAY_BLOCK = customProps(INDEX, '[data-mode="play"]')
// :root and [data-mode] are the same element (<html>), so var() resolves after both apply.
const MODES = {
  nucleus: { ...ROOT },
  nucleome: { ...ROOT, ...TRACKER_BLOCK },
  play: { ...ROOT, ...PLAY_BLOCK },
}

function resolve(tokens, value, seen = []) {
  return value.replace(/var\((--[\w-]+)\)/g, (_, name) => {
    assert.ok(!seen.includes(name), `token cycle through ${name}`)
    assert.ok(name in tokens, `${name} is not defined`)
    return resolve(tokens, tokens[name], [...seen, name])
  })
}

const token = (mode, name) => resolve(MODES[mode], `var(${name})`)

function hexColour(mode, name) {
  const value = token(mode, name).trim()
  assert.match(value, /^#[0-9a-f]{6}$/i, `${name} in ${mode} mode is a plain colour`)
  return value
}

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// Nucleus's gold signature: Tracker turns it purple, Play keeps it (it is Play's
// own colour: its Play buttons, a running game).
const GOLD_FAMILY = [
  '--color-gold', '--color-gold-light', '--color-gold-dark', '--color-gold-muted',
  '--gradient-gold', '--gradient-gold-hover', '--glow-gold', '--glow-gold-sm', '--glow-gold-intense',
]

test('Play re-points every token Tracker does, except the gold Play keeps', () => {
  const tracker = Object.keys(TRACKER_BLOCK).filter((name) => !GOLD_FAMILY.includes(name)).sort()
  assert.ok(tracker.length >= 20, 'found the Tracker block')
  assert.deepEqual(Object.keys(PLAY_BLOCK).sort(), tracker)
  for (const name of GOLD_FAMILY) assert.equal(token('play', name), token('nucleus', name))
})

test("Play's colours are all in one :root block, the mode block only points at it", () => {
  for (const [name, value] of Object.entries(PLAY_BLOCK)) {
    assert.match(value, /^var\(--(color|gradient|glow)-play[\w-]*\)$/, `${name}: ${value}`)
  }
  const hexes = Object.entries(ROOT).filter(([name, value]) => /-play/.test(name) && /#[0-9a-f]{3,8}\b/i.test(value))
  assert.ok(hexes.length >= 13, 'the Play purple tokens are defined in :root')
})

test('nothing outside Play reads the Play tokens, so Nucleus and Tracker are unchanged', () => {
  const playScoped = (rule) => rule.selector === ':root'
    || (rule.type === 'rule' && rule.selectors.every((selector) => /\[data-mode="play"\]|\.brand-toggle--play\b|\.brand-play-tag\b/.test(selector)))
    || (rule.parent?.type === 'atrule' && rule.parent.name === 'keyframes' && /Play$/.test(rule.parent.params))
  for (const [file, root] of [['index.css', INDEX], ['App.css', APP], ['BrandWordmark.css', WORDMARK]]) {
    root.walkDecls((decl) => {
      if (/var\(--(color|gradient|glow)-play/.test(decl.value)) {
        assert.ok(playScoped(decl.parent), `${file}: ${decl.parent.selector} { ${decl.prop} } reads a Play token`)
      }
    })
  }
  for (const value of Object.values(TRACKER_BLOCK)) assert.doesNotMatch(value, /-play/)
})

test('Play body text reads at least as well as Tracker body text', () => {
  for (const text of ['--color-text-primary', '--color-text-secondary', '--color-text-tertiary']) {
    for (const bg of ['--color-bg-deep', '--color-bg-base', '--color-bg-elevated', '--color-bg-surface']) {
      const play = contrast(hexColour('play', text), hexColour('play', bg))
      const tracker = contrast(hexColour('nucleome', text), hexColour('nucleome', bg))
      assert.ok(play >= tracker, `${text} on ${bg}: Play ${play.toFixed(2)} < Tracker ${tracker.toFixed(2)}`)
    }
  }
})

test("Play's accent and gold text read at least as well as Tracker's", () => {
  for (const fg of ['--color-accent', '--color-cyan', '--color-cyan-light', '--color-gold']) {
    for (const bg of ['--color-bg-base', '--color-bg-elevated', '--color-bg-surface']) {
      const play = contrast(hexColour('play', fg), hexColour('play', bg))
      const tracker = contrast(hexColour('nucleome', fg), hexColour('nucleome', bg))
      assert.ok(play >= tracker, `${fg} on ${bg}: Play ${play.toFixed(2)} < Tracker ${tracker.toFixed(2)}`)
    }
  }
})

// The primary button and the active header tab are the gold gradient face with
// the text colour .tab.active sets (App.css), unless the mode overrides it
// (index.css: nucleOME's purple faces take light text).
function primaryButtonContrast(mode) {
  const override = declValue(INDEX, `[data-mode="${mode}"] .tab.active`, 'color')
  const text = resolve(MODES[mode], override || declValue(APP, '.tab.active', 'color'))
  const face = token(mode, '--gradient-gold').match(/#[0-9a-f]{6}/gi)
  assert.equal(face.length, 2)
  return Math.min(...face.map((stop) => contrast(text, stop)))
}

test('the primary button reads at least as well in Play as in Tracker', () => {
  assert.ok(primaryButtonContrast('play') >= primaryButtonContrast('nucleome'))
  assert.ok(primaryButtonContrast('play') >= 4.5)
})

test('the dark text on accent buttons reads at least as well in Play as in Tracker', () => {
  for (const stop of [0, 1]) {
    const face = (mode) => token(mode, '--gradient-cyan').match(/#[0-9a-f]{6}/gi)[stop]
    const play = contrast(hexColour('play', '--color-bg-deep'), face('play'))
    const tracker = contrast(hexColour('nucleome', '--color-bg-deep'), face('nucleome'))
    assert.ok(play >= tracker, `stop ${stop}: Play ${play.toFixed(2)} < Tracker ${tracker.toFixed(2)}`)
  }
})

test('the wordmark has a Play look for every part of its Tracker look', () => {
  const declared = (rule) => rule.nodes.filter((node) => node.type === 'decl').map((decl) => decl.prop)
  const tracker = []
  WORDMARK.walkRules((rule) => {
    for (const selector of rule.selectors) {
      if (selector.includes('.brand-toggle--nucleome')) tracker.push([selector, declared(rule).sort()])
    }
  })
  assert.ok(tracker.length >= 5)
  for (const [selector, props] of tracker) {
    const play = selector.replace('.brand-toggle--nucleome', '.brand-toggle--play').replace('.brand-stats-tag', '.brand-play-tag')
    const found = []
    WORDMARK.walkRules((rule) => { if (rule.selectors.includes(play)) found.push(...declared(rule)) })
    assert.deepEqual([...new Set(found)].sort(), props, play)
  }
})

test("the word takes its mode's accent in Tracker and Play alike", () => {
  for (const mode of ['nucleome', 'play']) {
    const word = declValue(WORDMARK, `.brand-toggle--${mode} .vault-text`, 'color')
    assert.equal(resolve(MODES[mode], word), token(mode, '--color-accent'), mode)
  }
})
