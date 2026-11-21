'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { registerWindowIpc } = require('../../app/electron/ipc/window');

test('backend recovery marks the app quitting, schedules a fresh launch, then quits', () => {
  const handlers = {}, order = [], ctx = { isQuitting: false };
  registerWindowIpc({
    handleTrustedIpc: (name, fn) => { handlers[name] = fn; }, ctx,
    app: {
      relaunch: () => { assert.equal(ctx.isQuitting, true); order.push('relaunch'); },
      quit: () => { assert.equal(ctx.isQuitting, true); order.push('quit'); },
    },
  });
  handlers['app:relaunch']();
  assert.deepEqual(order, ['relaunch', 'quit']);
});
