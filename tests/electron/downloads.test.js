const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { EventEmitter } = require('events');

const { installDownloadDialog } = require('../../app/electron/shell/downloads');

function fakeItem(filename) {
  return { options: null, getFilename: () => filename, setSaveDialogOptions(options) { this.options = options; } };
}

test('a link download\'s Save As dialog is named after the file, never its URL', () => {
  const session = new EventEmitter();
  installDownloadDialog(session, () => 'C:\\Users\\someone\\Downloads');
  const item = fakeItem('Marth-pack.zip');
  session.emit('will-download', {}, item);
  assert.equal(item.options.title, 'Save Marth-pack.zip');
  assert.equal(item.options.defaultPath, path.join('C:\\Users\\someone\\Downloads', 'Marth-pack.zip'));
  assert.ok(!JSON.stringify(item.options).includes('token'));
});

test('a name with folders in it keeps only the file name', () => {
  const session = new EventEmitter();
  installDownloadDialog(session, () => '/home/someone/Downloads');
  const item = fakeItem('../../evil/name.dat');
  session.emit('will-download', {}, item);
  assert.equal(item.options.title, 'Save name.dat');
  assert.equal(path.basename(item.options.defaultPath), 'name.dat');
});

test('without a Downloads folder the dialog still gets the file name', () => {
  const session = new EventEmitter();
  installDownloadDialog(session, () => { throw new Error('no downloads path'); });
  const item = fakeItem('patch.xdelta');
  session.emit('will-download', {}, item);
  assert.deepEqual(item.options, { title: 'Save patch.xdelta', defaultPath: 'patch.xdelta' });
});

test('installing twice on one session adds one handler', () => {
  const session = new EventEmitter();
  installDownloadDialog(session, () => null);
  installDownloadDialog(session, () => null);
  assert.equal(session.listenerCount('will-download'), 1);
});
