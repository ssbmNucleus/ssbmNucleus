import { useContext, useState } from 'react'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { EditorContext } from '../../shared/lib/EditorContext'
import ApprovalCard from './ApprovalCard'
import { DownloadActivity } from './DownloadProgress'
import VaultModCards from './VaultModCards'
import StageModCard from './StageModCard'
import { activityLabel, phraseForTool } from './activity'
import { FailureNotice } from './TaskCards'
import { useDevDetails } from './devDetails'

// `compact` drops the download affordance: a file the assistant merely read
// is working material, and offering to save it reads as an instruction.
export function ModFileCards({ files = [], compact = false }) {
  const editor = useContext(EditorContext)
  const [error, setError] = useState('')
  const download = async file => {
    try {
      const blob = await api.blob(`/api/assistant/files/${file.file_id}`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = file.name; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err.message) }
  }
  return <div className="assistant-mod-files">{files.map(file => <article key={file.file_id}>
    {file.extension === '.png' && <img src={backendMediaUrl(`/api/assistant/files/${file.file_id}?preview=1`)} alt={file.name} />}
    <strong>{file.name}</strong><small>{Math.max(1, Math.round(file.size / 1024))} KB</small>
    <div>{!compact && <button type="button" onClick={() => download(file)}>Download file</button>}
      {file.extension === '.png' && !file.preview_only && editor?.editor?.texture && <button type="button"
        onClick={() => editor.setTextureRequest({ file, texture: editor.editor.texture, id: crypto.randomUUID() })}>Use on selected texture</button>}
    </div>
  </article>)}{error && <p role="alert" className="assistant-error">{error}</p>}</div>
}

// hsdraw covers a dozen operations that all used to collapse to "Mod file" --
// and then, worse, to their own internal names. These are what the operation
// did, said the way the person who asked for it would say it.
const HSDRAW_LABELS = {
  export_texture: 'Took a texture out of the file', texture_sheet: 'A picture of the textures',
  meshes: 'What the model is made of', export_model: 'Took the model out of the file',
  export_animation: 'Took an animation out', animations: 'The animations in the file',
  replace_texture: 'Put a texture back in', remove_meshes: 'Removed some parts',
  remove_triangles: 'Removed some geometry', render_stage: 'A picture of the stage',
}

const SKIN_LABELS = {
  texture_usage: 'Where this texture sits on the model', texture_sheet: 'A picture of the textures',
  highlight: 'Where that is on the model', texture: 'A texture from the skin',
}

// What the model-import steps are called on screen. "Source alignment" and
// "Model mesh selection" are the pipeline's words, not anybody else's. Chats
// stored by the retired first import still carry these operations (an
// `export` included); they show as these plain labels.
const MODEL_OPERATION_LABELS = {
  alignment: 'Lining your model up with the fighter',
  export: 'The costume file', revise: 'The repaired draft', import_model: 'Your model on a fighter',
  mesh: 'Which parts of the model to keep',
}

// A retexture saved by code when its turn ended (backend randall/recolor/autosave.py): the same receipt a
// save the user asked for makes, with `autosave` saying whether it made the vault item or updated it.
const AUTOSAVED = {
  saved: { label: 'Saved to your vault', status: 'Saved to your vault automatically' },
  updated: { label: 'Updated in your vault', status: 'Your vault copy now has this version' },
}

export function ModToolActivity({ tool, onDecision, selection, onSelect, onOpen }) {
  const devDetails = useDevDetails()
  const result = tool.result || {}
  const working = tool.status === 'running'
  const savedStage = tool.name === 'stage_lab' && result.vault_changed && result.variantId
  const autosaved = AUTOSAVED[result.autosave] || null
  const skinLab = ['skin_lab_open', 'skin_lab', 'skin_material'].includes(tool.name)
  const cloneTool = tool.name === 'create_clone_character'
  const modelTool = ['import_model', 'model_fit', 'model_candidate', 'model_mesh', 'model_revise', 'model_poses'].includes(tool.name)
  const label = autosaved ? autosaved.label
    : modelTool ? (MODEL_OPERATION_LABELS[result.operation] || 'Drafts fitted to fighters')
    : tool.name === 'generate_material' ? 'A new material'
    : tool.name === 'skin_material' ? (result.action === 'coverage' ? 'Where that colour is used' : phraseForTool(tool).done)
    : skinLab ? SKIN_LABELS[result.action] || 'Working on the skin'
    : tool.name === 'save_mod_copy' ? 'Saved a copy to your vault'
    : tool.name === 'open_vanilla_file' ? 'An original Melee costume'
    : cloneTool ? 'A new character' : HSDRAW_LABELS[result.operation] || activityLabel(tool)
  // A texture fetched to look at is working material; only a rendered result is
  // an artifact worth posting to the thread. The name still rides the collapsed
  // row, so what it read stays identifiable without opening it.
  // Receipts are persisted, so chats written before the backend sent `reading`
  // would stay a wall of cards forever. A texture read is recognisable by name,
  // which is enough to fold those too.
  const looksLikeTextureRead = /^Skin texture \d+\.png$/.test(result.files?.[0]?.name || '')
  const reading = Boolean(result.files?.length && (result.reading || looksLikeTextureRead))
  const summaryName = result.file?.name
    || (result.character && result.color ? `${result.character} ${result.color}` : '')
    // A texture INDEX is an internal position in the file. It identifies
    // nothing to the person reading the card.
    || (result.texture_index !== undefined ? 'one texture' : '')
    || (reading ? result.files[0]?.name : '')
  const hasDetail = Boolean(reading || result.roots || result.members || result.log || result.note)
  return <div className="assistant-mod-tool">
    {tool.approval && <ApprovalCard approval={tool.approval} onDecision={onDecision} />}
    {working && <DownloadActivity label={result.progress_label || phraseForTool(tool).working} />}
    <FailureNotice tool={tool} />
    {result.checkpoint_error && <p role="alert" className="assistant-error">{result.checkpoint_error}</p>}
    {!working && !result.error && !tool.approval && (hasDetail
      ? <details className="assistant-file-group assistant-mod-inspection">
        <summary>{label}{summaryName ? ` · ${summaryName}` : ''}<span className="assistant-file-chevron" aria-hidden="true">›</span></summary>
        <div className="assistant-file-body" tabIndex={0} role="region" aria-label={`${label} details`}>
          {reading && <ModFileCards files={result.files} compact />}
          {result.roots && <ul>{result.roots.map(name => <li key={name}>{name}</li>)}</ul>}
          {result.members && <ul>{result.members.map(item => <li key={item.name}>{item.name}</li>)}</ul>}
          {result.log && <pre>{result.log}</pre>}
          {result.note && <p>{result.note}</p>}
          {/* Developer details only: users never see dollars. */}
          {devDetails && Number.isFinite(result.cost_usd) && <p>Image generation: ${result.cost_usd.toFixed(4)}</p>}
        </div>
      </details>
      // Nothing to disclose: a plain label, not a control that opens an empty panel.
      : <div className="assistant-mod-inspection"><span className="assistant-file-label">{label}{summaryName ? ` · ${summaryName}` : ''}</span></div>)}
    {['save_mod_copy', 'stage_lab'].includes(tool.name) && result.vault_changed && <p role="status">{autosaved ? autosaved.status : 'Edited copy added to vault'}</p>}
    {cloneTool && !working && !result.error && result.character?.name && <p role="status">{result.character.name} is in Custom Characters · {result.character.costume_count} costumes</p>}
    {result.items?.length > 0 && <VaultModCards items={result.items} selection={selection} onSelect={onSelect} onOpen={onOpen} />}
    {savedStage ? <StageModCard item={{ kind: 'stage', id: result.variantId, folder: result.folder, stageCode: result.stageCode,
      name: result.name, image: result.files?.[0]?.file_id ? `/api/assistant/files/${result.files[0].file_id}?preview=1` : null }} />
      : !reading && <ModFileCards files={result.files} compact={!modelTool && !cloneTool} />}
  </div>
}

/** Several working steps as one line that changes as they run.

    The drafts, pictures and comparisons they lead to are NOT in here: they stay
    in the conversation as their own cards. This is the alignment/mesh/binding
    chatter that a person has no decision to make about. */
export function ModelWorkActivity({ tools = [] }) {
  const running = tools.some(tool => tool.status === 'running')
  const last = [...tools].reverse().find(tool => tool.status === 'running') || tools[tools.length - 1]
  const label = activityLabel(last)
  return <div className="assistant-file-activity assistant-model-work">
    <details className="assistant-file-group">
      <summary>{label}{tools.length > 1 ? ` · ${tools.length} steps` : ''}
        {running && <span className="assistant-work-pulse" aria-hidden="true"><i /></span>}
        <span className="assistant-file-chevron" aria-hidden="true">›</span></summary>
      <div className="assistant-file-body" tabIndex={0} role="region" aria-label="What Randall did along the way">
        {tools.map(tool => <ModToolActivity key={tool.id} tool={tool} />)}
      </div>
    </details>
  </div>
}
