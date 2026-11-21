const test = require('node:test');
const assert = require('node:assert/strict');
const { createUpdateMonitor } = require('../../app/electron/updates/update-monitor');

function fixture(check) {
  let time = 0, id = 0;
  const timers = new Map(), notifications = [];
  const monitor = createUpdateMonitor({ check, notify: value => notifications.push(value), now: () => time,
    setTimer: (fn, ms) => { const key = ++id; timers.set(key, { fn, due: time + ms }); return key; },
    clearTimer: key => timers.delete(key) });
  return { monitor, timers, notifications, setTime: value => { time = value; },
    async fire() { const [key, timer] = [...timers][0]; timers.delete(key); time = timer.due; timer.fn(); await monitor.check(); } };
}

test('startup checks after 15 seconds, then every six hours with one timer', async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return null; });
  f.monitor.start(); f.monitor.start();
  assert.equal(f.timers.size, 1);
  assert.equal([...f.timers.values()][0].due, 15000);
  await f.monitor.checkIfDue(); assert.equal(calls, 0);
  await f.fire(); assert.equal(calls, 1);
  assert.equal([...f.timers.values()][0].due, 15000 + 21600000);
  assert.deepEqual(f.notifications, [null]);
});

test('offline startup retries in five minutes and wake/focus never spam checks', async () => {
  let calls = 0;
  const update = { version: '0.8.2' };
  const f = fixture(async () => { if (++calls === 1) throw new Error('offline'); return update; });
  f.monitor.start(); await f.fire();
  assert.equal(f.monitor.getStatus().error, 'offline');
  assert.equal([...f.timers.values()][0].due, 315000);
  f.setTime(314999);
  await f.monitor.checkIfDue(); await f.monitor.checkIfDue(); assert.equal(calls, 1);
  f.setTime(315001);
  await Promise.all([f.monitor.checkIfDue(), f.monitor.checkIfDue()]);
  assert.equal(calls, 2);
  assert.deepEqual(f.notifications, [update]);
  assert.equal(f.monitor.getStatus().error, null);
  assert.equal(f.timers.size, 1);
});

test('manual and background checks share the same promise and broadcast once', async () => {
  let finish, calls = 0;
  const f = fixture(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
  f.monitor.start(); f.setTime(15000);
  const background = f.monitor.checkIfDue();
  const manual = f.monitor.check();
  assert.equal(background, manual);
  await Promise.resolve(); assert.equal(calls, 1);
  finish({ version: '0.8.2' });
  assert.deepEqual(await manual, { success: true, update: { version: '0.8.2' } });
  assert.equal(f.notifications.length, 1);
});

test('manual check works without starting background scheduling and null clears stale update', async () => {
  let result = { version: '0.8.2' };
  const f = fixture(async () => result);
  await f.monitor.check(); result = null; await f.monitor.check();
  assert.deepEqual(f.notifications, [{ version: '0.8.2' }, null]);
  assert.equal(f.monitor.getStatus().update, null);
  assert.equal(f.timers.size, 0);
});

test('a failed refresh retains the last verified update and retries sooner', async () => {
  let fail = false;
  const f = fixture(() => { if (fail) throw new Error('network down'); return { version: '0.8.2' }; });
  f.monitor.start(); await f.monitor.check(); fail = true;
  assert.deepEqual(await f.monitor.check(), { success: false, error: 'network down' });
  assert.equal(f.monitor.getStatus().update.version, '0.8.2');
  assert.equal(f.notifications.length, 1);
  assert.equal([...f.timers.values()][0].due, 300000);
});

test('shutdown cancels timers and makes late check completion inert', async () => {
  let finish;
  const f = fixture(() => new Promise(resolve => { finish = resolve; }));
  f.monitor.start(); const pending = f.monitor.check(); await Promise.resolve();
  f.monitor.stop(); finish({ version: '0.8.2' }); await pending;
  assert.equal(f.timers.size, 0); assert.deepEqual(f.notifications, []);
  assert.equal(f.monitor.getStatus().checkedAt, null);
  await f.monitor.checkIfDue(); assert.equal(f.timers.size, 0);
});

test('a disappearing renderer does not turn a verified check into a failure', async () => {
  const monitor = createUpdateMonitor({check: () => ({version:'0.8.2'}), notify: () => {throw new Error('window closed');}});
  assert.equal((await monitor.check()).success, true);
  assert.equal(monitor.getStatus().error, null);
});
