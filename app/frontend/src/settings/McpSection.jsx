/**
 * McpSection - "Connect your own AI": the command that adds Nucleus as an MCP server to Claude Code, Codex or Claude
 * Desktop, one client at a time (a pill row picks it). Shown only in builds with the assistant (Settings.jsx, the AI
 * category). The command comes from the main process (electron/ipc/system.js 'mcp:launch'); docs/dev/APP_MCP.md is
 * the long form.
 */
import { useEffect, useState } from 'react'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { claudeCodeCommand, claudeDesktopConfig, codexCommand } from './mcpCommands'

export const MCP_CLIENTS = [
  { id: 'claude-code', label: 'Claude Code', hint: 'Run it in a terminal.', text: claudeCodeCommand },
  { id: 'codex', label: 'Codex', hint: 'Run it in a terminal.', text: codexCommand },
  { id: 'claude-desktop', label: 'Claude Desktop', hint: 'Settings > Developer > Edit Config, paste it in, restart.',
    text: claudeDesktopConfig },
]

function CopyBlock({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    playSound('start')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="mcp-connect-block">
      <pre className="mcp-connect-text">{text}</pre>
      <button type="button" className={`mcp-copy-button${copied ? ' is-copied' : ''}`} onMouseEnter={playHoverSound}
        onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  )
}

export function McpView({ launch, client = MCP_CLIENTS[0].id, onPick }) {
  const picked = MCP_CLIENTS.find(c => c.id === client) || MCP_CLIENTS[0]
  return (
    <section className="settings-section mcp-connect-section">
      <h3>Connect your own AI</h3>
      <p className="ai-card-lede">Give Claude Code, Codex or Claude Desktop Randall&apos;s tools for your vault.</p>
      {launch ? <>
        <div className="ai-pills" role="tablist" aria-label="Your AI app">
          {MCP_CLIENTS.map(c => <button key={c.id} type="button" role="tab" aria-selected={c.id === picked.id}
            className={`ai-pill${c.id === picked.id ? ' is-on' : ''}`} onMouseEnter={playHoverSound}
            onClick={() => onPick?.(c.id)}>{c.label}</button>)}
        </div>
        <p className="ai-card-hint">{picked.hint}</p>
        <CopyBlock text={picked.text(launch)} />
      </> : <p className="ai-card-hint">Available in the desktop app.</p>}
      <p className="ai-card-note">Its calls skip Randall&apos;s Approve buttons, so check what it asks to run.</p>
    </section>
  )
}

export default function McpSection() {
  const [launch, setLaunch] = useState(null)
  const [client, setClient] = useState(MCP_CLIENTS[0].id)
  useEffect(() => {
    let live = true
    window.electron?.getMcpLaunch?.().then(value => { if (live) setLaunch(value) }).catch(() => {})
    return () => { live = false }
  }, [])
  return <McpView launch={launch} client={client} onPick={setClient} />
}
