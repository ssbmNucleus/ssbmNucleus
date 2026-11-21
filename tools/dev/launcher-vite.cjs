'use strict';

// This child owns Vite. Shutdown uses its private IPC channel, never PID lookup.
const path = require('node:path');
const { pathToFileURL } = require('node:url');
async function runVite(vite, root, channel = process) {
  // The parent may have disappeared while the Vite module was loading.
  if (!channel.connected) return;
  let server;
  let stopping = false;
  let closePromise;
  async function stop() {
    stopping = true;
    if (server) await (closePromise ||= server.close());
    if (channel.connected) channel.disconnect();
  }
  function fail(error) {
    console.error(error.stack || error);
    channel.exitCode = 1;
    if (channel.connected) channel.disconnect();
  }
  channel.on('message', message => {
    if (message?.type === 'stop') stop().catch(fail);
  });
  channel.on('disconnect', () => { stop().catch(fail); });
  try {
    const loaded = await vite.loadConfigFromFile({ command: 'serve', mode: 'development' }, path.join(root, 'vite.config.js'), root);
    if (!loaded) throw new Error('Could not load frontend/vite.config.js');
    // Parent writes the handoff after HTTP readiness. Do not let the config plugin
    // delete another session's handoff when this child closes.
    const plugins = (loaded.config.plugins || []).flat(Infinity).filter(p => p?.name !== 'vite-port-handoff');
    server = await vite.createServer({ ...loaded.config, configFile: false, root, plugins,
      server: { ...loaded.config.server, host: 'localhost', port: 3000, strictPort: false, open: false } });
    if (stopping) return stop();
    await server.listen();
    if (stopping) return stop();
    const address = server.httpServer.address();
    if (!address || typeof address !== 'object') throw new Error('Vite did not bind a TCP port');
    channel.send({ type: 'listening', port: address.port });
  } catch (error) {
    fail(error);
    await stop();
  }
}
module.exports = { runVite };
if (require.main === module) {
  const root = process.cwd();
  import(pathToFileURL(path.join(root, 'node_modules/vite/dist/node/index.js')).href)
    .then(vite => runVite(vite, root)).catch(error => {
      console.error(error.stack || error);
      process.exitCode = 1;
      if (process.connected) process.disconnect();
    });
}
