'use strict';

// Bug #64: games must show on the phone while a big desktop sync is still
// uploading. Two phone-side pieces are pure enough to test here: the crawl
// hands each page's rows to the caller (so the list can paint before the last
// page), and an empty list explains itself instead of reading "0 synced".

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const load = (name) => import(`data:text/javascript;base64,${Buffer.from(
  fs.readFileSync(path.join(__dirname, '..', '..', '..', 'services', 'mobile', 'src', name), 'utf8')).toString('base64')}`);

let status;
let account;
test.before(async () => {
  status = await load('library-status.js');
  account = await load('account-generation.js');
});

test('crawl hands every page its rows so far', async () => {
  const pages = [
    { games: [{ id: 3 }, { id: 2 }], next_before: 2 },
    { games: [{ id: 1 }], next_before: null },
  ];
  const seen = [];
  const games = await account.fetchAccountPages({
    readPage: async () => pages.shift(),
    token: 't', generation: 'g', isCurrent: () => true,
    onPage: (n, soFar) => seen.push([n, soFar.map((g) => g.id)]),
  });
  assert.deepEqual(seen, [[2, [3, 2]], [3, [3, 2, 1]]]);
  assert.equal(games.length, 3);
});

test('a non-empty list needs no explanation', () => {
  assert.equal(status.emptyLibraryText({ synced: 10, listed: 4, codes: [] }), null);
});

test('an empty vault says games arrive per batch', () => {
  const t = status.emptyLibraryText({ synced: 0, listed: 0, codes: ['ALYJ#98'] });
  assert.match(t, /as each batch uploads/);
});

test('uploaded-but-unattributed says so, with the count and the codes', () => {
  // the exact state of the #64 reporter's vault on the day: ~18k rows, all
  // from before the code they play under now
  const t = status.emptyLibraryText({ synced: 18451, listed: 0, codes: ['ALYJ#98'] });
  assert.match(t, /18,451 games uploaded so far/);
  assert.match(t, /ALYJ#98/);
  assert.match(t, /still syncing/);
});

test('mid-crawl empty is a loading state, not a verdict', () => {
  assert.equal(status.emptyLibraryText({ synced: 1000, listed: 0, codes: [], loading: true }),
    'Loading your games…');
});
