'use strict';

// Synthetic events only: two fighters, percent jumps, and one rollback.
function replayBytes(fids = [-123, -122, -121, -122, -121, -120]) {
  const sizes = { 0x36: 0x2f8, 0x38: 0x54, 0x3a: 12, 0x3c: 8 };
  const event = (cmd) => {
    const b = Buffer.alloc(sizes[cmd] + 1);
    b[0] = cmd;
    return b;
  };
  const table = Buffer.alloc(2 + Object.keys(sizes).length * 3);
  table[0] = 0x35;
  table[1] = table.length - 1;
  Object.entries(sizes).forEach(([cmd, size], i) => {
    table[2 + i * 3] = Number(cmd);
    table.writeUInt16BE(size, 3 + i * 3);
  });
  const start = event(0x36);
  start.set([3, 18, 0], 1);
  start.writeUInt16BE(31, 0x13);
  for (let port = 0; port < 4; port++) {
    start[0x65 + port * 0x24] = port === 0 ? 2 : 9;
    start[0x66 + port * 0x24] = port < 2 ? 0 : 3;
  }
  const events = [table, start];
  for (const fid of fids) {
    const fs = event(0x3a);
    fs.writeInt32BE(fid, 1);
    events.push(fs);
    for (let port = 0; port < 2; port++) {
      const post = event(0x38);
      post.writeInt32BE(fid, 1);
      post[5] = port;
      post[7] = port === 0 ? 1 : 18;
      post.writeUInt16BE(port === 1 && fid > -123 ? 75 : 14, 8);
      post.writeFloatBE((port ? 1 : -1) * 15, 0xa);
      post.writeFloatBE(port ? -1 : 1, 0x12);
      post.writeFloatBE(port ? Math.max(0, fid + 123) * 8 : 0, 0x16);
      post.writeFloatBE(60, 0x1a);
      post[0x21] = 4;
      events.push(post);
    }
    const fe = event(0x3c);
    fe.writeInt32BE(fid, 1);
    fe.writeInt32BE(fid, 5);
    events.push(fe);
  }
  const raw = Buffer.concat(events);
  const header = Buffer.from([123, 85, 3, 114, 97, 119, 91, 36, 85, 35, 108, 0, 0, 0, 0]);
  header.writeInt32BE(raw.length, 11);
  return new Uint8Array(Buffer.concat([header, raw]));
}

module.exports = { replayBytes };
