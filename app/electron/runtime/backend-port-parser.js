'use strict';

const MAX_PENDING = 64 * 1024;

class BackendPortParser {
  constructor(maxPending = MAX_PENDING) {
    this.maxPending = maxPending;
    this.pending = '';
    this.discarding = false;
  }

  feed(chunk) {
    const text = String(chunk);
    const records = (this.pending + text).split(/\r?\n/);
    this.pending = records.pop();
    const ports = [];
    for (const record of records) {
      if (this.discarding) {
        this.discarding = false;
        continue;
      }
      const match = record.match(/^\s*BACKEND_PORT:(\d+)\s*$/);
      if (!match) continue;
      const port = Number(match[1]);
      if (Number.isInteger(port) && port >= 1 && port <= 65535) ports.push(port);
    }
    if (this.pending.length > this.maxPending) {
      this.pending = '';
      this.discarding = true;
    }
    return ports;
  }
}

module.exports = { BackendPortParser, MAX_PENDING };
