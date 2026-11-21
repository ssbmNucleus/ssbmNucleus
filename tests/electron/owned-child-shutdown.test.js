'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { terminateOwnedChild } = require('../../app/electron/runtime/owned-child-shutdown');

test('an already exited child never reuses its stale PID for shutdown', async () => {
  await terminateOwnedChild({ pid: 12345, exitCode: 0, killed: false }, {
    platform: 'win32',
    exec: () => assert.fail('must not target an exited child PID'),
  });
});

test('failed Windows tree shutdown falls back only to the owned child handle', async () => {
  const commands = [];
  const signals = [];
  const child = { pid: 4321, killed: false, kill: (signal) => signals.push(signal) };
  await terminateOwnedChild(child, {
    platform: 'win32', isWine: false,
    exec: (command, callback) => { commands.push(command); callback(new Error('failed')); },
  });
  assert.deepEqual(commands, ['taskkill /F /T /PID 4321']);
  assert.deepEqual(signals, ['SIGKILL']);
  assert.equal(commands.some((command) => command.includes('/IM')), false);
});

test('Unix fallback targets the owned process group then exact child', async () => {
  const groupPids = [];
  const signals = [];
  const child = { pid: 987, killed: false, kill: (signal) => signals.push(signal) };
  await terminateOwnedChild(child, {
    platform: 'linux',
    killGroup: (pid) => { groupPids.push(pid); throw new Error('gone'); },
  });
  assert.deepEqual(groupPids, [-987]);
  assert.deepEqual(signals, ['SIGKILL']);
});
