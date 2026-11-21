/**
 * CreationToolkitSection - "Creation toolkit": where porting fighters from other games (native_port) and building
 * custom stages (stage_workbench) come from. The installer does not carry them; the app MCP forwards both to a copy
 * of Nucleus's source the user sets up once (backend/randall/mcp/toolkit.py, tools/creation/SETUP.md). This card
 * only says so and opens the setup guide; the user's own AI does the connecting (connect_creation_toolkit).
 * Shown in builds with the assistant, in Settings > AI beside the MCP card.
 */
import { playHoverSound, playSound } from '../shared/audio/sounds'

// The public repo's copy of tools/creation/SETUP.md (backend/randall/mcp/toolkit.py REPO_URL, branch main).
export const CREATION_TOOLKIT_GUIDE = 'https://github.com/ssbmNucleus/ssbmNucleus/blob/main/tools/creation/SETUP.md'

export default function CreationToolkitSection() {
  const openGuide = () => {
    playSound('start')
    if (window.electron?.openExternal) window.electron.openExternal(CREATION_TOOLKIT_GUIDE)
    else window.open(CREATION_TOOLKIT_GUIDE, '_blank')
  }
  return (
    <section className="settings-section creation-toolkit-section">
      <h3>Creation toolkit</h3>
      <p className="ai-card-lede">Port fighters from other games and build custom stages with your own AI. It is a
        separate setup: ask your AI to set it up, or follow the guide.</p>
      <div className="ai-chips">
        <span className="ai-chip">Set up once</span>
        <span className="ai-chip">Windows</span>
        <span className="ai-chip">Stages need the .NET SDK</span>
      </div>
      <div className="model-tools-actions">
        <button type="button" className="restore-button" onMouseEnter={playHoverSound} onClick={openGuide}>
          Setup guide ↗
        </button>
      </div>
    </section>
  )
}
