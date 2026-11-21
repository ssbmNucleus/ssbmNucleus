'use strict';

// The renderer's half of nucleus:// delivery: it says when it can receive
// links and acknowledges each one it has handled.
function registerProtocolIpc({ handleTrustedIpc, handoffs }) {
  handleTrustedIpc('protocol:renderer-ready', () => handoffs.rendererReady());
  handleTrustedIpc('protocol:ack', (_event, id) => handoffs.acknowledge(id));
}

module.exports = { registerProtocolIpc };
