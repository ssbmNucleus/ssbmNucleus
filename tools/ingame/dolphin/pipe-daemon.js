#!/usr/bin/env node

/*
 * Persistent bridge to Slippi Dolphin's named-pipe controller input.
 *
 * Reconnecting to \\.\pipe\slippibot<port> for every input loses the final
 * RELEASE / stick-recenter when the socket closes, so buttons and the control
 * stick get stuck ("spamming"). libmelee avoids this by holding ONE connection
 * open for the whole session. This daemon does the same: it keeps the Dolphin
 * pipe open and accepts high-level commands over a local TCP socket, executing
 * the press/hold/release (and stick tilt/recenter) timing on the persistent
 * connection. It reconnects automatically if Dolphin restarts.
 *
 * Client command lines (newline-terminated), each answered with "OK\n"/"ERR ...":
 *   TAP <BTN> <ms>            press, hold ms, release
 *   PRESS <BTN> / RELEASE <BTN>
 *   TILT <STICK> <x> <y> <ms> tilt, hold ms, recenter   (STICK = MAIN|C)
 *   HOLDTILT <STICK> <x> <y>  tilt and leave held
 *   STICK <STICK> <x> <y>     set stick, no recenter (alias of HOLDTILT)
 *   TRIG <L|R> <v>            set an analog trigger 0..1
 *   NEUTRAL                   release everything, center sticks
 *   RAW <protocol line>       send a raw pipe line verbatim
 *
 * Usage: node pipe-daemon.js [--port <slippibot port=1>] [--tcp <port=48010>]
 */

const net = require('net');
const fs = require('fs');
const path = require('path');

const LOG_FILE = path.join(__dirname, '..', '..', '..', 'app', 'scratch', 'ingame', 'dolphin', 'live', 'pipe-daemon.log');

const args = process.argv.slice(2);
function flag(name, def) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const PIPE_PORT = parseInt(flag('port', '1'), 10);
const TCP_PORT = parseInt(flag('tcp', '48010'), 10);
const PIPE_PATH = `\\\\.\\pipe\\slippibot${PIPE_PORT}`;

const BUTTONS = ['A', 'B', 'X', 'Y', 'Z', 'L', 'R', 'START', 'D_UP', 'D_DOWN', 'D_LEFT', 'D_RIGHT'];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let dolphin = null; // persistent socket to the Dolphin pipe

function dolphinConnect() {
  return new Promise((resolve, reject) => {
    if (dolphin && !dolphin.destroyed) {
      resolve(dolphin);
      return;
    }
    const s = net.connect(PIPE_PATH);
    let settled = false;
    s.on('connect', () => {
      settled = true;
      dolphin = s;
      log(`connected to ${PIPE_PATH}`);
      resolve(s);
    });
    s.on('error', (err) => {
      if (!settled) {
        settled = true;
        dolphin = null;
        reject(err);
      }
    });
    s.on('close', () => {
      if (dolphin === s) {
        dolphin = null;
        log('Dolphin pipe closed; will reconnect on next command');
      }
    });
  });
}

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  // eslint-disable-next-line no-console
  console.log(`[pipe-daemon] ${line}`);
  try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    fs.appendFileSync(LOG_FILE, `${line}\n`);
  } catch (e) {
    // ignore log failures
  }
}

async function exec(line) {
  const s = await dolphinConnect();
  const sent = [];
  const send = (l) => {
    sent.push(l);
    return s.write(`${l}\n`);
  };
  const parts = line.trim().split(/\s+/);
  const op = (parts[0] || '').toUpperCase();

  switch (op) {
    case 'TAP': {
      const btn = parts[1].toUpperCase();
      const ms = parseInt(parts[2] || '50', 10);
      send(`PRESS ${btn}`);
      send('FLUSH');
      await sleep(ms);
      send(`RELEASE ${btn}`);
      send('FLUSH');
      break;
    }
    case 'PRESS':
    case 'RELEASE':
      send(`${op} ${parts[1].toUpperCase()}`);
      send('FLUSH');
      break;
    case 'TILT': {
      const stick = parts[1].toUpperCase();
      const ms = parseInt(parts[4] || '100', 10);
      send(`SET ${stick} ${parts[2]} ${parts[3]}`);
      send('FLUSH');
      await sleep(ms);
      send(`SET ${stick} 0.5 0.5`);
      send('FLUSH');
      break;
    }
    case 'HOLDTILT':
    case 'STICK':
      send(`SET ${parts[1].toUpperCase()} ${parts[2]} ${parts[3]}`);
      send('FLUSH');
      break;
    case 'TRIG':
      send(`SET ${parts[1].toUpperCase()} ${parts[2]}`);
      send('FLUSH');
      break;
    case 'NEUTRAL':
      for (const b of BUTTONS) send(`RELEASE ${b}`);
      send('SET MAIN 0.5 0.5');
      send('SET C 0.5 0.5');
      send('SET L 0');
      send('SET R 0');
      send('FLUSH');
      break;
    case 'RAW':
      send(line.trim().slice(4));
      break;
    default:
      throw new Error(`unknown command: ${op || '<none>'}`);
  }
  log(`exec "${line.trim()}" -> wrote [${sent.join(' | ')}] writableLength=${s.writableLength}`);
  await sleep(20); // let the final FLUSH be read for a frame before returning
}

// Serialize commands so press/release pairs never interleave.
let queue = Promise.resolve();
function enqueue(line) {
  const run = queue.then(() => exec(line));
  queue = run.catch(() => {});
  return run;
}

const server = net.createServer((client) => {
  let buf = '';
  client.on('data', (chunk) => {
    buf += chunk.toString();
    let idx;
    // eslint-disable-next-line no-cond-assign
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx);
      buf = buf.slice(idx + 1);
      if (!line.trim()) continue;
      enqueue(line).then(
        () => client.write('OK\n'),
        (err) => client.write(`ERR ${err.message}\n`),
      );
    }
  });
  client.on('error', () => {});
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    log(`TCP ${TCP_PORT} already in use; a daemon is already running. Exiting.`);
    process.exit(0);
  }
  log(`server error: ${err.message}`);
  process.exit(1);
});

server.listen(TCP_PORT, '127.0.0.1', () => {
  log(`listening on 127.0.0.1:${TCP_PORT}, bridging to ${PIPE_PATH}`);
});
