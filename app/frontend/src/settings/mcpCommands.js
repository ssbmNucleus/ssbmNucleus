// The text McpSection shows for connecting the user's own AI to Nucleus over MCP.
// `launch` is what electron/ipc/system.js answers for 'mcp:launch': the executable
// and its arguments (installed: the exe and --mcp; a checkout: electron.exe, the app
// folder and --mcp). docs/dev/APP_MCP.md is the long form.

// One shell word: plain flags stay bare, anything else (paths, spaces) goes in double
// quotes. Backslashes are left alone so a Windows path reads the same in PowerShell,
// cmd and Git Bash.
export function shellWord(value) {
  const text = String(value)
  return /^[A-Za-z0-9_\-.=/:]+$/.test(text) ? text : `"${text.replace(/"/g, '\\"')}"`
}

function commandLine(launch) {
  return [launch.command, ...launch.args].map(shellWord).join(' ')
}

export function claudeCodeCommand(launch) {
  return `claude mcp add --scope user nucleus -- ${commandLine(launch)}`
}

export function codexCommand(launch) {
  return `codex mcp add nucleus -- ${commandLine(launch)}`
}

export function claudeDesktopConfig(launch) {
  return JSON.stringify({ mcpServers: { nucleus: { command: launch.command, args: [...launch.args] } } }, null, 2)
}
