'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { BackendPortParser } = require('../../app/electron/runtime/backend-port-parser');

test('accepts a complete announcement split at every chunk boundary', () => {
  const record = 'BACKEND_PORT:5001\n';
  for (let split = 1; split < record.length; split += 1) {
    const parser = new BackendPortParser();
    assert.deepEqual(parser.feed(record.slice(0, split)), []);
    assert.deepEqual(parser.feed(record.slice(split)), [5001]);
  }
});

test('does not accept partial, malformed, embedded, or out-of-range ports', () => {
  const parser = new BackendPortParser();
  assert.deepEqual(parser.feed('BACKEND_PORT:50'), []);
  assert.deepEqual(parser.feed('01\nnoise BACKEND_PORT:6000\n'), [5001]);
  assert.deepEqual(parser.feed('BACKEND_PORT:0\nBACKEND_PORT:65536\nBACKEND_PORT:12x\n'), []);
});

test('bounds an unterminated record and resumes after its newline', () => {
  const parser = new BackendPortParser(8);
  assert.deepEqual(parser.feed('xxxxxxxxx'), []);
  assert.deepEqual(parser.feed('BACKEND_PORT:42\n'), []);
  assert.deepEqual(parser.feed('BACKEND_PORT:43\n'), [43]);
});
