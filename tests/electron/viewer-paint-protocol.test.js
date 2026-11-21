'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const ViewerManager = require('../../app/electron/viewers/viewer-manager');
const StreamViewerManager = require('../../app/electron/viewers/stream-viewer-manager');

for (const Manager of [ViewerManager, StreamViewerManager]) {
  test(`${Manager.name} preserves pair ownership and correlation across transport`, () => {
    const manager = new Manager();
    const sent = [];
    manager.isConnected = true;
    manager.pipeClient = { write: data => sent.push(JSON.parse(data)) };
    manager.ws = { send: data => sent.push(JSON.parse(data)) };
    const command = {
      type: 'updateTexture', memberId: 'nana', index: 0,
      sessionId: 'pair-2', requestId: 'paint-7', data: 'aW1hZ2U=',
    };
    assert.equal(manager.send(command), true);
    assert.deepEqual(sent, [command]);
    manager.isConnected = false;
    assert.equal(manager.send(command), false);
    assert.equal(sent.length, 1);
  });

  test(`${Manager.name} tags paired replies and reports disconnect once`, () => {
    const manager = new Manager();
    const received = [];
    manager.viewerSessionId = 'transport-new';
    manager.onMessage('all', message => received.push(message));
    const reply = {
      type: 'exportPaintPair', sessionId: 'pair-2', requestId: 'save-1',
      success: true, members: [{ memberId: 'popo', data: 'cA==' }, { memberId: 'nana', data: 'bg==' }],
    };
    manager.handleMessage(reply);
    manager.notifyDisconnected('connection lost');
    manager.notifyDisconnected('process exited');
    assert.deepEqual(received, [
      { ...reply, viewerSessionId: 'transport-new' },
      { type: 'disconnected', error: 'connection lost', viewerSessionId: 'transport-new' },
    ]);
  });
}

test('embedded pipe closure notifies the active painting session', () => {
  const manager = new ViewerManager();
  manager.pipeClient = new EventEmitter();
  manager.viewerSessionId = 'embedded-session';
  manager.isConnected = true;
  const received = [];
  manager.onMessage('disconnected', message => received.push(message));
  manager.setupPipeHandlers();
  manager.pipeClient.emit('error', new Error('broken pipe'));
  manager.pipeClient.emit('close');
  assert.equal(manager.isConnected, false);
  assert.equal(received.length, 1);
  assert.equal(received[0].viewerSessionId, 'embedded-session');
});

test('fragmented embedded pair replies preserve two independent index-zero textures', () => {
  const manager = new ViewerManager();
  manager.pipeClient = new EventEmitter();
  manager.viewerSessionId = 'embedded-session';
  const received = [];
  manager.onMessage('all', message => received.push(message));
  manager.setupPipeHandlers();
  const reply = {
    type: 'textures', sessionId: 'pair', requestId: 'textures-1',
    textures: [{ memberId: 'popo', index: 0, textureId: 'popo:0' },
      { memberId: 'nana', index: 0, textureId: 'nana:0' }],
  };
  const wire = JSON.stringify(reply) + '\n';
  manager.pipeClient.emit('data', Buffer.from(wire.slice(0, 51)));
  assert.equal(received.length, 0);
  manager.pipeClient.emit('data', Buffer.from(wire.slice(51)));
  assert.deepEqual(received, [{ ...reply, viewerSessionId: 'embedded-session' }]);
});

test('streaming socket closure notifies the active painting session', async () => {
  const socket = new EventEmitter();
  socket.send = () => {};
  const manager = new StreamViewerManager({ WebSocket: class { constructor() { return socket; } } });
  manager.viewerSessionId = 'stream-session';
  const received = [];
  manager.onMessage('disconnected', message => received.push(message));
  const connected = manager._connectWebSocket();
  socket.emit('open');
  await connected;
  socket.emit('close');
  assert.equal(manager.isConnected, false);
  assert.deepEqual(received, [{
    type: 'disconnected', error: 'Streaming viewer WebSocket closed', viewerSessionId: 'stream-session',
  }]);
});
