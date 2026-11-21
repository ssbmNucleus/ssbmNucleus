'use strict';

// The MCP discovery file: where a running Nucleus tells its `--mcp` relay (relay.js) how to reach the backend.
// <userData>/mcp-endpoint.json = {"url":"http://127.0.0.1:<port>/api/mcp","token":"<backend token>","pid":<main pid>}
// userData is per user, so the token is exactly as private as the app's own profile. Written once the backend is
// up, removed on quit (only by the process that wrote it). NUCLEUS_MCP_DISCOVERY moves it, for both sides (tests).
const fs = require('fs');
const path = require('path');

const FILE_NAME = 'mcp-endpoint.json';
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

function discoveryPath(userData, env = process.env) {
  return env.NUCLEUS_MCP_DISCOVERY || path.join(userData, FILE_NAME);
}

function writeDiscovery(file, { port, token, pid }) {
  const body = JSON.stringify({ url: `http://127.0.0.1:${port}/api/mcp`, token, pid }, null, 2);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // Renamed into place, so a relay never reads half a file.
  const temporary = `${file}.${pid}.tmp`;
  fs.writeFileSync(temporary, body, { mode: 0o600 });
  fs.renameSync(temporary, file);
}

function removeDiscovery(file, pid) {
  try {
    if (JSON.parse(fs.readFileSync(file, 'utf8')).pid !== pid) return false;
    fs.unlinkSync(file);
    return true;
  } catch {
    return false;
  }
}

function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

// The endpoint a live app wrote, or null (no file, unreadable, not loopback, or its process is gone).
function readDiscovery(file, isAlive = pidAlive) {
  let data;
  try {
    data = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
  if (!data || typeof data.url !== 'string' || typeof data.token !== 'string' || !data.token) return null;
  let url;
  try {
    url = new URL(data.url);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' || !LOOPBACK.has(url.hostname)) return null;
  if (!isAlive(data.pid)) return null;
  return { url: data.url, token: data.token, pid: data.pid };
}

module.exports = { FILE_NAME, discoveryPath, writeDiscovery, removeDiscovery, readDiscovery, pidAlive };
