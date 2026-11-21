'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const moduleUrl = pathToFileURL(path.join(__dirname, '..', '..', '..', 'services', 'mobile', 'src', 'account-generation.js')).href;
let account;

class Storage {
  constructor(entries = {}) { this.values = new Map(Object.entries(entries)); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

test.before(async () => {
  // This repository is CommonJS, while the phone sources are browser ESM.
  // A data URL loads the exact source as ESM without invoking the site build.
  const source = fs.readFileSync(new URL(moduleUrl), 'utf8');
  account = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
});

test('account A cache is unavailable after adopting account B', () => {
  const storage = new Storage({
    [account.TOKEN_KEY]: 'account-a-token-0001',
    [account.GENERATION_KEY]: 'generation-a',
    [account.CODES_KEY]: '["A#1"]',
  });
  const cachedA = account.cacheForGeneration({ games: ['a-game'] }, 'generation-a');

  account.replaceToken('account-b-token-0002', storage);

  assert.notEqual(account.generationFor(storage), 'generation-a');
  assert.equal(account.cacheValueForGeneration(cachedA, account.generationFor(storage)), undefined);
  assert.equal(storage.getItem(account.CODES_KEY), null);
});

test('token rotation deliberately invalidates same-owner cache', () => {
  const storage = new Storage({
    [account.TOKEN_KEY]: 'owner-token-old-0001',
    [account.GENERATION_KEY]: 'before-rotation',
  });
  const cached = account.cacheForGeneration({ games: ['owned'] }, 'before-rotation');

  account.replaceToken('owner-token-new-0002', storage);

  assert.equal(account.cacheValueForGeneration(cached, account.generationFor(storage)), undefined);
});

test('fragment adoption invalidates cache before boot can read it', () => {
  const storage = new Storage({
    [account.TOKEN_KEY]: 'account-a-token-0001',
    [account.GENERATION_KEY]: 'generation-a',
  });
  const cachedA = account.cacheForGeneration({ games: ['private-a'] }, 'generation-a');

  assert.equal(account.claimTokenFromHash('#t=account-b-token-0002', storage), true);
  assert.equal(account.tokenFor(storage), 'account-b-token-0002');
  assert.equal(account.cacheValueForGeneration(cachedA, account.generationFor(storage)), undefined);
});

test('token switch during pagination cannot publish mixed pages', async () => {
  let token = 'account-a-token-0001';
  let generation = 'generation-a';
  const requested = [];

  await assert.rejects(account.fetchAccountPages({
    token,
    generation,
    isCurrent: (expectedToken, expectedGeneration) =>
      token === expectedToken && generation === expectedGeneration,
    readPage: async (request) => {
      requested.push(request);
      token = 'account-b-token-0002';
      generation = 'generation-b';
      return { games: ['a-game'], next_before: 'older' };
    },
  }), /account changed/);

  assert.equal(requested.length, 1);
  assert.equal(requested[0].token, 'account-a-token-0001');
});
