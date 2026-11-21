import test from 'node:test'
import assert from 'node:assert/strict'
import { claudeCodeCommand, claudeDesktopConfig, codexCommand, shellWord } from './mcpCommands.js'

const installed = { command: 'C:\\Users\\me\\AppData\\Local\\Programs\\SSBM Nucleus\\SSBM Nucleus.exe', args: ['--mcp'] }
const checkout = { command: 'C:\\src\\app\\node_modules\\electron\\dist\\electron.exe', args: ['C:\\src\\app', '--mcp'] }

test('the Claude Code and Codex commands quote the exe path and keep --mcp bare', () => {
  assert.equal(claudeCodeCommand(installed),
    'claude mcp add --scope user nucleus -- "C:\\Users\\me\\AppData\\Local\\Programs\\SSBM Nucleus\\SSBM Nucleus.exe" --mcp')
  assert.equal(codexCommand(installed),
    'codex mcp add nucleus -- "C:\\Users\\me\\AppData\\Local\\Programs\\SSBM Nucleus\\SSBM Nucleus.exe" --mcp')
  assert.equal(claudeCodeCommand(checkout),
    'claude mcp add --scope user nucleus -- "C:\\src\\app\\node_modules\\electron\\dist\\electron.exe" "C:\\src\\app" --mcp')
})

test('the Claude Desktop config is valid JSON naming the exe and its arguments', () => {
  const config = JSON.parse(claudeDesktopConfig(installed))
  assert.deepEqual(config, { mcpServers: { nucleus: { command: installed.command, args: ['--mcp'] } } })
  assert.deepEqual(JSON.parse(claudeDesktopConfig(checkout)).mcpServers.nucleus.args, ['C:\\src\\app', '--mcp'])
})

test('shell words: flags and plain paths stay bare, spaces and quotes are quoted', () => {
  assert.equal(shellWord('--mcp'), '--mcp')
  assert.equal(shellWord('/Applications/Nucleus.app/Contents/MacOS/Nucleus'), '/Applications/Nucleus.app/Contents/MacOS/Nucleus')
  assert.equal(shellWord('/opt/SSBM Nucleus/nucleus'), '"/opt/SSBM Nucleus/nucleus"')
  assert.equal(shellWord('a"b'), '"a\\"b"')
})
