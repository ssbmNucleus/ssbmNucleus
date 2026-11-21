'use strict';

// Settings > data location. These schedule or cancel a move only; the copy
// itself runs offline at the next launch (storage/storage-host.js).
function registerStorageIpc({ handleTrustedIpc, ctx, storageHost }) {
  handleTrustedIpc('storage:status', () => storageHost.invoke('status'));
  handleTrustedIpc('storage:choose', () => storageHost.invoke('choose', null, ctx.mainWindow));
  handleTrustedIpc('storage:schedule', (_event, destination) => storageHost.invoke('schedule', destination));
  handleTrustedIpc('storage:cancel', () => storageHost.invoke('cancel'));
}

module.exports = { registerStorageIpc };
