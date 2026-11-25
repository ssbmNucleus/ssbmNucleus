import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_COVER_BYTES, SAME_GAME, askBeforeShelfAdd, coverProblem, findSameGame, replaceQuestion, sameGame, shelfAddBody,
  shelfDoneText, startShelfAdd,
} from './shelfAdd.js'

const refusal = (existing) => Object.assign(new Error('"PokeMelee" is already on your Unlocked shelf.'),
  { status: 409, data: { success: false, code: SAME_GAME, existing } })

function poster(...answers) {
  const posts = []
  const post = async (path, body) => {
    posts.push({ path, body })
    const answer = answers.shift()
    if (answer instanceof Error) throw answer
    return answer
  }
  return { post, posts }
}

test('without a cover the add is plain JSON, with one it is a form carrying the picture', () => {
  assert.deepEqual(shelfAddBody({ artifactId: 'a', name: 'PokeMelee', description: '', replace: null }),
    { artifactId: 'a', name: 'PokeMelee', description: '' })
  const picture = new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' })
  const form = shelfAddBody({ patchId: 'p', name: 'PokeMelee', replace: undefined }, picture)
  assert.ok(form instanceof FormData)
  assert.deepEqual([...form.keys()], ['patchId', 'name', 'cover'])
  assert.equal(form.get('name'), 'PokeMelee')
  assert.equal(form.get('cover').size, 4)
})

test('only a 409 naming the same game asks to replace', () => {
  const existing = { id: '0123456789ab', name: 'PokeMelee' }
  assert.deepEqual(sameGame(refusal(existing)), existing)
  assert.equal(sameGame(Object.assign(new Error('busy'), { status: 409, data: { job_id: 'j' } })), null)
  assert.equal(sameGame(Object.assign(new Error('x'), { status: 400, data: { code: SAME_GAME, existing } })), null)
  assert.equal(sameGame(refusal({ name: 'no id' })), null)
  assert.equal(sameGame(null), null)
})

test('a yes replaces the game the shelf named, with the same fields and cover', async () => {
  const existing = { id: '0123456789ab', name: 'PokeMelee' }
  const { post, posts } = poster(refusal(existing), { job_id: 'j' })
  const asked = []
  const picture = new Blob(['x'], { type: 'image/png' })
  const answer = await startShelfAdd({ artifactId: 'a', name: 'pokemelee', description: 'New' }, {
    cover: picture, post, confirm: async (message, options) => { asked.push([message, options]); return true },
  })
  assert.deepEqual(answer, { job_id: 'j' })
  assert.equal(posts.length, 2)
  assert.equal(posts[1].path, '/api/play/shelf/add')
  assert.equal(posts[1].body.get('replace'), '0123456789ab')
  assert.equal(posts[1].body.get('artifactId'), 'a')
  assert.ok(posts[1].body.get('cover'))
  assert.match(asked[0][0], /^"PokeMelee" is already on your Unlocked shelf\. Replace it with this one\?/)
  assert.match(asked[0][0], /with the new cover/)
  assert.equal(asked[0][1].confirmText, 'Replace')
})

test('a no adds nothing and says the old game was kept', async () => {
  const { post, posts } = poster(refusal({ id: '0123456789ab', name: 'PokeMelee' }))
  await assert.rejects(startShelfAdd({ patchId: 'p' }, { post, confirm: async () => false }),
    (err) => err.kept === true && err.message === '"PokeMelee" was left as it is.' && typeof err.data === 'object')
  assert.equal(posts.length, 1)
})

test('any other refusal, or one for a replace already asked for, is not asked about', async () => {
  const busy = Object.assign(new Error('That game is running. Close it first.'), { status: 409, data: {} })
  let asked = 0
  const confirm = async () => { asked++; return true }
  await assert.rejects(startShelfAdd({ patchId: 'p' }, { ...poster(busy), confirm }), /running/)
  await assert.rejects(startShelfAdd({ patchId: 'p', replace: 'x' },
    { ...poster(refusal({ id: 'y', name: 'Other' })), confirm }), /already on your Unlocked shelf/)
  assert.equal(asked, 0)
})

test('the export asks before it builds, and a failed lookup does not stop it', async () => {
  const gets = []
  const get = async (path, options) => { gets.push([path, options]); return { existing: { id: 'e', name: 'PokeMelee', running: true } } }
  let question = ''
  const yes = await askBeforeShelfAdd('PokeMelee', { get, confirm: async (message) => { question = message; return true } })
  assert.deepEqual(yes, { go: true, replace: 'e' })
  assert.deepEqual(gets[0], ['/api/play/shelf/same', { query: { name: 'PokeMelee' } }])
  assert.match(question, /running now: close it/)
  assert.match(question, /Its saves, its cover and its place on the shelf are kept/)
  assert.deepEqual(await askBeforeShelfAdd('PokeMelee', { get, confirm: async () => false }), { go: false })
  const none = async () => ({ existing: null })
  assert.deepEqual(await askBeforeShelfAdd('New', { get: none, confirm: async () => assert.fail('asked') }),
    { go: true, replace: null })
  const down = async () => { throw new Error('Backend unreachable') }
  assert.deepEqual(await askBeforeShelfAdd('New', { get: down, confirm: async () => assert.fail('asked') }),
    { go: true, replace: null })
  assert.equal(await findSameGame('x', async () => ({ existing: { name: 'no id' } })), null)
})

test('a cover picture is checked when it is chosen, with the backend limits', () => {
  assert.equal(coverProblem(null), null)
  assert.equal(coverProblem({ type: 'image/jpeg', size: 1024 }), null)
  assert.equal(coverProblem({ type: 'image/webp', size: MAX_COVER_BYTES }), null)
  assert.equal(coverProblem({ type: 'image/png', size: MAX_COVER_BYTES + 1 }), 'That picture is too large. The limit is 8 MB.')
  assert.equal(coverProblem({ type: 'image/svg+xml', size: 10 }), 'Choose a PNG, JPEG, GIF or WebP picture.')
  assert.equal(coverProblem({ type: '', size: 10 }), 'Choose a PNG, JPEG, GIF or WebP picture.')
})

test('the done line says when a game was replaced', () => {
  assert.equal(shelfDoneText({ name: 'PokeMelee' }), 'PokeMelee is on your Unlocked shelf.')
  assert.equal(shelfDoneText({ name: 'PokeMelee', replaced: true }), 'PokeMelee was replaced on your Unlocked shelf.')
  assert.equal(shelfDoneText(null, 'Patch'), 'Patch is on your Unlocked shelf.')
  assert.match(replaceQuestion({ name: 'A' }), /The old version is removed\.$/)
})
