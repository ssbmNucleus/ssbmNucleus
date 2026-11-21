const { ipcRenderer } = require('electron');
let pending = null;
function render(progress) {
  const target = document.getElementById('status');
  if (!target) { pending = progress; return; }
  const phase = progress?.phase;
  target.textContent = phase === 'verified' ? 'Copy verified. Opening your library…'
    : phase === 'copying' ? 'Copying your data…'
    : phase === 'verifying' ? 'Checking the copied files and databases…'
    : 'Preparing and verifying your data move…';
}
ipcRenderer.on('storage:progress', (_event, progress) => render(progress));
window.addEventListener('DOMContentLoaded', () => { if (pending) render(pending); });
