import { visibleAssistantText } from '../chat/visibleText'
import { Fragment, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, authenticatedFetch } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { readAssistantStream } from './stream'
import { applyPendingInput, applyTurnProgress, mergeTranscript, orderedMessageParts, showWorkingBubble } from './transcript'
import { assistantAccess, lowUsageWarning } from './access'
import { activityLabel, INTERMEDIATE_TOOLS } from './activity'
import { DecisionCard, FailureNotice, ResultCard } from './TaskCards'
import { decisionOptions, deliveryResult, settledEnvelope } from './taskEnvelope'
import { getEntitlement, getPatreonToken, buildPatreonAuthorizeUrl, ENTITLEMENT_EVENT, PATREON_CAMPAIGN_URL } from '../../shared/account/entitlement'
import { getAccessToken } from '../../shared/account/account'
import Icon from './AssistantIcon'
import ApprovalCard from './ApprovalCard'
import WebsiteModCards from './WebsiteModCards'
import VaultModCards from './VaultModCards'
import { collectWebsiteCards } from './websiteCards'
import { SmoothText, TypingBubble } from './ChatMotion'
import DownloadReceipt from './DownloadReceipt'
import DownloadProgress from './DownloadProgress'
import LongRunningNotice from './LongRunningNotice'
import UsageRow from './UsageRow'
import { EditorContext } from '../../shared/lib/EditorContext'
import { ModFileCards, ModToolActivity, ModelWorkActivity } from './ModFileCards'
import DownloadApprovalDialog from './DownloadApprovalDialog'
import SlippiApprovalDialog from './SlippiApprovalDialog'
import FileReadActivity, { groupFileReads, VaultReadActivity } from './FileReadActivity'
import PortraitActivity from './PortraitActivity'
import ProjectToolCard from './ProjectToolCard'
import GameTestCard from './GameTestCard'
import StudioToolCard from './StudioCards'
import { isStudioTool, studioContext } from './studio'
import WorkbenchPanel, { useWorkbenchOpen, PICTURE_DRAG_TYPE } from './WorkbenchPanel'
import { workbenchState } from './workbench'
import { setDevDetails, useDevDetails } from './devDetails'
import { restoreFailedDraft, sendGate } from './sending'
import QueuedPrompts from './PendingMessages'
import { followUpFor, launchableTasks, labelFor, mismatchOf, placeholderFor, previousUserText, showStartAnother, startableTasks, taskOf, terminalReceipt } from './taskModes'
import { StartAnother, TaskIcon, TaskMismatch } from './TaskPicker'
import Composer from './Composer'
import { contextNotes, outgoingContext, pickerFor, pickPlaceholder } from './startPick'
import { rosterOf } from '../../vault/picker/costumePicks'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import { ChatLayout, ChatSidebar, ChatHeader, ChatAccount, RandallIdentity, CopyButton, JoinFreeUnlock } from '../chat/ChatUI'
import ChatReportModal, { ReportChatButton } from '../chat/ChatReportModal'
import { budgetFromEntitlement } from '../chat/chatReport'
import './AssistantPanel.css'

const ROOT = '/api/assistant'
const ACTIVE_KEY = 'nucleus_assistant_chat'
// Tool activity is named in `activity.js` -- one plain phrase per tool, and a
// test that fails when a new tool arrives without one. Nothing in this panel
// may fall back to a raw tool name.
// Only for a backend whose /status serves no tasks: with the starting-point
// chips, the plain composer is the "just ask" path and needs no starters.
const STARTERS = [
  ['Explore website mods', 'Help me explore mods on the Nucleus website.'],
  ['Explain Nucleus features', 'Explain the features available in Nucleus.'],
  ['Create a mod', 'Help me create a mod.'],
]
// Model import cannot target an Ice Climbers pair; /status `import_fighters` is
// the backend's list, this the fallback for a backend that does not serve it.
const NOT_IMPORTABLE = ['Ice Climbers']
const keyOf = (item) => `${item.character}:${item.id}`
const Markdown = ({ children }) => <ReactMarkdown remarkPlugins={[remarkGfm]}
  components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}>{children}</ReactMarkdown>

// Exported for ToolCard.test.js.
export function ToolCard({ tool, selection, toggleSelection, onOpenVault, onOpenProject, onUndo, onDecision, onDownload, onDownloadMany, cards, account, busy, downloadBusy, directDownload, chatId, visible, liveGameTool, gameInPanel, onAsk, onActivation, studio }) {
  const result = tool.result || {}
  // The model import, routed by its reply's `studio_import` tag before any
  // name: an older chat's studio stage 10 is also called `test_in_game`.
  if (isStudioTool(tool, studio?.active)) return <StudioToolCard tool={tool} context={studio} />
  // The live game plays in the workbench beside the chat; one embed at a time.
  if (tool.name === 'test_in_game' && tool.id === gameInPanel) return <p className="assistant-game-moved" role="status">
    <span className="assistant-work-pulse" aria-hidden="true"><i /></span>Playing in the workbench on the right</p>
  if (tool.name === 'test_in_game') return <GameTestCard tool={tool} chatId={chatId} visible={visible} live={tool.id === liveGameTool} />
  // A tool that carries a task envelope is rendered from its OUTCOME, before
  // any legacy tool status is consulted: the engine marks a finished call
  // `done` whatever the task achieved, and reading that first is how a partial
  // delivery said "Put into the game you play - Done".
  const envelope = settledEnvelope(tool)
  if (envelope && ['deliver_to_game', 'undo_delivery'].includes(tool.name)) {
    const props = deliveryResult(envelope)
    const pendingActivation = (envelope.facts || {}).activation === 'pending'
      || (envelope.limitations || []).some(line => /Slippi Launcher/i.test(line))
    const actions = []
    if (pendingActivation && onActivation) {
      actions.push({ id: 'activation', label: 'Check Slippi selection', onSelect: onActivation })
    }
    if (props.undoable && onAsk) {
      // There is no delivery-undo ENDPOINT yet (assistant_bp has no
      // /deliveries route), so this is honestly labelled as asking Randall
      // rather than dressed up as a direct control. The producer's own
      // `how_to_undo` sentence names the receipt, so it is what gets sent.
      actions.push({ id: 'undo', label: 'Ask Randall to take it back out',
        onSelect: () => onAsk(props.receiptId
          ? `Undo delivery receipt ${props.receiptId}.`
          : 'Take that costume back out of my game.') })
    }
    return <>
      <ResultCard {...props} title={tool.name === 'undo_delivery' ? 'Taking it back out' : props.title}
        actions={actions} />
      {envelope.next && (() => {
        const options = decisionOptions(envelope.next)
        // The chosen answer's own words ("Make it my Slippi game."), so two answers that
        // share an action are not both sent as "Yes: deliver to game."
        return <DecisionCard request={{ id: envelope.next.id, prompt: envelope.next.prompt, options }}
          onRespond={(_, id) => onAsk?.((options.find(option => option.id === id) || {}).say
            || `Yes: ${String(id).replace(/_/g, ' ')}.`)} />
      })()}
    </>
  }
  // The retired first model import's tools (model_fit, model_candidate,
  // model_mesh, model_revise) are not produced any more; a chat stored with
  // them falls through to the plain labelled step below.
  if (['create_clone_character', 'import_model', 'generate_material', 'skin_material', 'skin_lab_open', 'skin_lab', 'stage_lab_open', 'stage_lab', 'hsdraw', 'hsdraw_capabilities', 'open_vault_file', 'open_vanilla_file', 'inspect_mod_file', 'unpack_mod_file', 'save_mod_copy'].includes(tool.name)) return <ModToolActivity tool={tool} onDecision={onDecision} selection={selection} onSelect={toggleSelection} onOpen={onOpenVault} />
  if (tool.name === 'present_vault_skins') return <>
    {result.error && <p className="assistant-error" role="alert">{result.error}</p>}
    {result.items?.length > 0 && <VaultModCards items={result.items} selection={selection} onSelect={toggleSelection} onOpen={onOpenVault} />}
  </>
  if (tool.name === 'preview_portrait') return <PortraitActivity tool={tool} />
  if (['list_projects', 'inspect_project', 'create_project', 'install_project_mods'].includes(tool.name)) return <ProjectToolCard tool={tool} onDecision={onDecision} onOpenProject={onOpenProject} />
  if (tool.name === 'review_download_safety') return result.error ? <p className="assistant-error" role="alert">{result.error}</p> : null
  const websiteTool = ['search_website_mods', 'inspect_website_mod', 'download_website_mod', 'download_website_mods', 'set_website_mod_like'].includes(tool.name)
  if (tool.status === 'running' && !cards.length && !Object.keys(result).length && !tool.approval) return null
  if (websiteTool && !cards.length && !result.bulk_download && !result.error && !result.imported_count && !result.failed?.length && !result.warnings?.length && result.website_total !== 0) return null
  return <div className={`assistant-tool ${websiteTool ? 'assistant-tool--website' : ''} ${tool.status === 'error' ? 'assistant-tool--error' : ''}`}>
    {!websiteTool && tool.status !== 'running' && <div className="assistant-tool-heading">
      <span className={tool.status === 'running' ? 'assistant-working' : ''} aria-hidden="true">
        {tool.status === 'running' ? '◌' : tool.status === 'done' ? '✓' : '·'}
      </span>
      <strong>{activityLabel(tool)}</strong>
      <span>{{ running: 'Working', awaiting_approval: 'Waiting for you', error: 'Failed', done: 'Done', denied: 'Declined', expired: 'Expired', cancelled: 'Stopped', interrupted: 'Interrupted' }[tool.status] || tool.status}</span>
    </div>}
    {tool.approval && !websiteTool && <ApprovalCard approval={tool.approval} onDecision={onDecision} />}
    <FailureNotice tool={tool} />
    {/* A search that found nothing is a search result, not a dead end: say what
        was looked for, and what the user can do next without Randall. */}
    {result.website_total === 0 && <div className="assistant-no-match">
      <p>{result.tried?.length ? result.note : 'Nothing on the mod website matched that.'}</p>
      <p className="assistant-settled-next">You can change the words and search again, look through your own vault,
        or paste a link to a mod page you have found.</p>
    </div>}
    {cards.length > 0 && <WebsiteModCards cards={cards} search={result} onDecision={onDecision} onDownload={onDownload} onDownloadMany={onDownloadMany} busy={downloadBusy} account={account} directDownload={directDownload} />}
    {result.bulk_download && <DownloadProgress tool={tool} />}
    {websiteTool && (result.imported_count > 0 || result.choice_required || (result.detected && !result.imported_count))
      && <DownloadReceipt result={result} onOpenVault={onOpenVault} />}
    {!websiteTool && result.imported_count !== undefined && <p className="assistant-import-summary" role="status">
      {result.imported_count} added to vault{result.skipped_count > 0 ? ` · ${result.skipped_count} already owned` : ''}
      {result.fixed_count > 0 ? ` · ${result.fixed_count} Slippi fixes` : ''}</p>}
    {result.failed?.length > 0 && <details open><summary>Files that could not be imported</summary>
      <ul>{result.failed.map((file, index) => <li key={index}>{file.name}: {file.error}</li>)}</ul>
    </details>}
    {result.warnings?.length > 0 && <details><summary>Some preview images could not be added</summary>
      <ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
    </details>}
    {result.total !== undefined && <p>{result.total} matching costume{result.total === 1 ? '' : 's'}
      {result.next_offset !== null && result.next_offset !== undefined ? ' · Ask to see more' : ''}</p>}
    {result.items?.length > 0 && <VaultModCards items={result.items} selection={selection}
      onSelect={toggleSelection} onOpen={onOpenVault} />}
    {result.image && <img className="assistant-preview" src={backendMediaUrl(result.image)} alt="New costume portrait preview" />}
    {result.sources?.map((source, index) => <details key={index}>
      <summary>{source.title}</summary><Markdown>{source.excerpt}</Markdown>
    </details>)}
    {/* A fallback search dropped the character/author/tag filters to find these,
        so its sentence stays visible ON the results, not only when there are none. */}
    {result.note && (!websiteTool || result.failed?.length > 0 || (result.tried?.length && cards.length > 0))
      && <p className="assistant-broadened">{result.note}</p>}
    {result.action_id && <button className="assistant-secondary" disabled={busy || result.undone}
      onClick={() => onUndo(result.action_id)}>{result.undone ? 'Undone' : 'Undo organization'}</button>}
  </div>
}

export default function AssistantPanel({ visible, context, account, vaultMetadata, onOpenVault, onOpenProject, onRefresh }) {
  const editorBridge = useContext(EditorContext)
  // Every successful skin edit checkpoints a working DAT; an editor showing
  // the same costume adopts it, so chat edits appear there without reopening.
  const publishSkinCheckpoint = useCallback(result => {
    if (!result?.checkpoint_file?.file_id || !result?.skin_target?.character) return
    editorBridge?.publishCheckpoint?.({
      file: result.checkpoint_file, target: result.skin_target,
      revision: result.revision || 0, sessionId: result.session_id, action: result.action,
    })
  }, [editorBridge])
  const [attachedFiles, setAttachedFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef(null)
  const [status, setStatus] = useState(null)
  // True once the first /status request has answered or failed: until then the
  // empty state cannot know whether this build has starting points or old starters.
  const [statusSettled, setStatusSettled] = useState(false)
  const [entitlement, setEntitlement] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [deletingChat, setDeletingChat] = useState(null)
  const access = assistantAccess(status, entitlement)
  const [chats, setChats] = useState([])
  const [chatId, setChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const liveGameTool = messages.flatMap(message => message.tools || []).filter(tool => tool.result?.game_test).at(-1)?.id
  // What Randall is making, shown beside the chat (not in the Texture Lab sidebar).
  const workbench = useMemo(() => workbenchState(messages, liveGameTool), [messages, liveGameTool])
  // What the chat's model imports say beyond each reply: fighters, pictures by path.
  const studio = useMemo(() => studioContext(messages), [messages])
  const [workbenchOpen, setWorkbenchOpen] = useWorkbenchOpen()
  const inEditor = Boolean(editorBridge?.editor)
  const gameInPanel = workbench.game && workbenchOpen && !inEditor ? workbench.game : null
  const gameTool = workbench.game ? messages.flatMap(message => message.tools || []).find(tool => tool.id === workbench.game) : null
  const notifiedProjectChanges = useRef(new Set())
  const [draft, setDraft] = useState('')
  // The chat's declared task (a launchable family id), null for a free "Ask"
  // chat. Picked on an empty chat; read from the chat once it has messages.
  const [task, setTask] = useState(null)
  // The empty chat's starting point for a task with a `picker`: the costume a
  // recolor starts from, the fighter an import goes on (CostumePicker's pick) or
  // the stage a stage recolor starts from (StagePicker's). Picked in the composer
  // (StartPickControl's popover).
  const [startPick, setStartPick] = useState(null)
  const [selection, setSelection] = useState([])
  const [busy, setBusy] = useState(false)
  const [directDownload, setDirectDownload] = useState(null)
  const [downloadBusy, setDownloadBusy] = useState(false)
  const downloadRef = useRef(false), streamingMessage = useRef(null)
  useEffect(() => { if (!downloadBusy) setDirectDownload(null) }, [downloadBusy])
  const [recovering, setRecovering] = useState(false)
  const [runId, setRunId] = useState(null)
  const [replyRunId, setReplyRunId] = useState(null)
  const [pendingInputs, setPendingInputs] = useState([])
  const [changingInput, setChangingInput] = useState(false)
  const [resumeInput, setResumeInput] = useState(null)
  const changingInputRef = useRef(false), inputRetry = useRef(null)
  const [error, setError] = useState('')
  // A remembered chat is about to open and close the history sidebar, so start
  // closed: opening it first made the sidebar flash open, then slam shut.
  const [showHistory, setShowHistory] = useState(() => {
    try { return !localStorage.getItem(ACTIVE_KEY) } catch { return true }
  })
  const [reporting, setReporting] = useState(false)
  // Loading only when a remembered chat is about to open: an empty chat's composer
  // starts in the middle of the page, and starting "loading" (composer at the
  // bottom) made it glide up on every launch.
  const [loadingChat, setLoadingChat] = useState(() => {
    try { return Boolean(localStorage.getItem(ACTIVE_KEY)) } catch { return false }
  })
  const awaitingApproval = messages.some(message => message.tools?.some(tool => tool.approval?.status === 'pending'))
  const modalApproval = messages.flatMap(message => message.tools || []).find(tool => tool.approval?.status === 'pending' && (tool.approval.website_mods?.length || tool.approval.slippi_review))?.approval
  const downloadApproval = modalApproval?.website_mods?.length ? modalApproval : null
  const slippiApproval = modalApproval?.slippi_review ? modalApproval : null
  const [vaultPresence, setVaultPresence] = useState({})
  const websiteCards = collectWebsiteCards(messages, vaultPresence)
  const websitePostIds = [...websiteCards.keys()].sort((a, b) => a - b).join(',')
  const downloadRevision = messages.flatMap(message => (message.tools || []).filter(tool =>
    ['download_website_mod', 'download_website_mods'].includes(tool.name)).map(tool =>
    `${tool.id}:${tool.status}:${tool.result?.imported_count || 0}:${tool.result?.skipped_count || 0}`)).join('|')
  useEffect(() => {
    if (!visible || !websitePostIds) return
    let current = true
    const ids = websitePostIds.split(',').map(Number)
    const batches = []
    for (let index = 0; index < ids.length; index += 500) batches.push(ids.slice(index, index + 500))
    Promise.all(batches.map(post_ids => api.post(`${ROOT}/website/vault-status`, { post_ids })))
      .then(results => { if (current) setVaultPresence(Object.assign({}, ...results.map(result => result.in_vault || {}))) })
      .catch(() => { /* Keep known card state if the local backend is unavailable. */ })
    return () => { current = false }
  }, [visible, websitePostIds, vaultMetadata, downloadRevision])
  const activeDownload = downloadBusy || messages.some(message => message.tools?.some(tool => ['download_website_mod', 'download_website_mods'].includes(tool.name) && ['running', 'awaiting_approval'].includes(tool.status)))
  const scrollRef = useRef(null), inputRef = useRef(null), controller = useRef(null)
  const shownApproval = useRef(null)
  const follow = useRef(true), busyRef = useRef(false), loadVersion = useRef(0)
  const settingsClose = useRef(null)
  // Every starting point (the empty chat's chips and the pill's menu show a
  // not-yet-built one disabled); `startable` is what can actually start a chat
  // (the sidebar rows, "Start another", a mismatch nudge).
  const tasks = useMemo(() => launchableTasks(status), [status])
  const startable = useMemo(() => startableTasks(tasks), [tasks])
  const taskLocked = messages.length > 0
  // The new-chat screen: the composer in the middle of the page (Composer `start`).
  const startScreen = !loadingChat && messages.length === 0
  const picker = taskLocked ? null : pickerFor(startable, task)
  const importFighters = useMemo(() => rosterOf({ only: status?.import_fighters, exclude: NOT_IMPORTABLE }), [status])
  // Only an empty, usable chat shows its task's placeholder; the Patreon lock
  // keeps its own wording (and its own wrapping).
  const taskPlaceholder = access.ready && !taskLocked
    ? pickPlaceholder(picker, startPick) || placeholderFor(startable, task, null) : null
  // Low on usage for what this chat runs next (a retexture, an import, a plain turn): a line above the message bar.
  // It only warns; sending stays as it is. At the limit itself the composer is locked and says so instead.
  const lowUsage = access.ready ? lowUsageWarning(entitlement, { task, picker, pick: startPick, importing: studio.active }) : null
  // The row dot in the history: only the open chat's state is known here.
  const lastReply = messages.findLast(message => message.role === 'assistant')
  const openChatStatus = busy || recovering ? 'running'
    : lastReply && (lastReply.error || lastReply.status === 'error') ? 'error' : null
  const modelLabel = status?.model === 'z-ai/glm-5.3-flash' ? 'GLM 5.3 Flash' : status?.model || 'Connecting…'
  const devDetails = useDevDetails()
  const openSettings = () => { setShowHistory(false); setShowSettings(true) }
  const closeSettings = () => { setShowSettings(false); setShowHistory(true); requestAnimationFrame(() => document.getElementById('nucleus-chat-history')?.querySelector('[aria-label="Randall settings"]')?.focus()) }
  const openPatreon = () => window.dispatchEvent(new CustomEvent('nucleus:open-settings', { detail: { section: 'patreon' } }))
  useEffect(() => { if (showSettings) settingsClose.current?.focus() }, [showSettings])
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 160)}px`
    }
  }, [draft, visible])

  const refreshChats = () => api.get(`${ROOT}/chats`).then(data => setChats(data.chats))
  const refreshStatus = () => api.get(`${ROOT}/status`).then(setStatus).catch(err => setError(err.message))
    .finally(() => setStatusSettled(true))
  // Probing shells out to the CLI, so it runs when the panel opens, not on a timer.
  const refreshEntitlement = async () => {
    const token = getPatreonToken()
    try {
      const next = await getEntitlement({ force: true })
      if (token === getPatreonToken()) setEntitlement(next)
      return next
    } catch {
      if (token === getPatreonToken()) setEntitlement({ checkFailed: true })
      return { checkFailed: true }
    }
  }
  const remember = (id) => { try { id ? localStorage.setItem(ACTIVE_KEY, id) : localStorage.removeItem(ACTIVE_KEY) } catch { /* storage disabled */ } }
  const notifyProjectChanges = receipts => {
    for (const tool of receipts) {
      if (tool.result?.project_changed && !notifiedProjectChanges.current.has(tool.id)) {
        notifiedProjectChanges.current.add(tool.id)
        window.dispatchEvent(new Event('nucleus:project-changed'))
      }
    }
  }
  const receiveChat = data => {
    notifyProjectChanges(data.messages.flatMap(message => message.tools || []))
    const accepted = data.reply_run_id ? (data.pending_inputs || []).filter(item => item.mode === 'steer') : []
    const incoming = [...data.messages, ...accepted.filter(item => !data.messages.some(message => message.id === item.id))
      .map(item => ({ ...item, role: 'user', input_kind: 'steer' }))]
    setMessages(previous => mergeTranscript(previous, incoming, streamingMessage.current))
    const active = Boolean(data.active_run_id || controller.current)
    const downloading = Boolean(data.download_run_ids?.length || data.messages.some(message =>
      message.tools?.some(tool => ['download_website_mod', 'download_website_mods'].includes(tool.name) && ['running', 'awaiting_approval'].includes(tool.status))))
    downloadRef.current = downloading; setDownloadBusy(downloading)
    busyRef.current = active; setBusy(active); setRecovering(Boolean(data.active_run_id))
    setRunId(data.reply_run_id || data.download_run_ids?.[0] || data.active_run_id)
    setReplyRunId(data.reply_run_id || null)
    setPendingInputs(data.pending_inputs || [])
  }
  const openChat = async (id) => {
    if (busyRef.current || uploading || changingInputRef.current) return
    const version = ++loadVersion.current
    setLoadingChat(true); setError('')
    try {
      const data = await api.get(`${ROOT}/chats/${id}`)
      if (version !== loadVersion.current) return
      setChatId(id); remember(id); receiveChat(data); setTask(taskOf(data, data.messages)); setSelection([]); setAttachedFiles([]); setShowHistory(false)
      setStartPick(null)
      follow.current = true
    } catch (err) {
      if (version === loadVersion.current) { setError(err.message); remember(null) }
    } finally { if (version === loadVersion.current) setLoadingChat(false) }
  }

  useEffect(() => {
    refreshChats().catch(err => setError(err.message))
    let saved
    try { saved = localStorage.getItem(ACTIVE_KEY) } catch { /* storage disabled */ }
    if (saved) openChat(saved)
    else setLoadingChat(false)
    return () => controller.current?.abort()
  }, [])
  useEffect(() => { if (visible) { refreshStatus(); refreshEntitlement() } }, [visible])
  useEffect(() => {
    const changed = () => { setEntitlement(null); refreshEntitlement() }
    window.addEventListener(ENTITLEMENT_EVENT, changed)
    return () => window.removeEventListener(ENTITLEMENT_EVENT, changed)
  }, [])
  useEffect(() => {
    if (!recovering || !chatId) return
    let alive = true
    const timer = setInterval(async () => {
      try {
        const data = await api.get(`${ROOT}/chats/${chatId}`)
        if (!alive) return
        receiveChat(data)
        if (!data.active_run_id) {
          onRefresh(); refreshChats().catch(() => {})
        }
      } catch (err) { if (alive) setError(err.message) }
    }, 1500)
    return () => { alive = false; clearInterval(timer) }
  }, [recovering, chatId])
  useEffect(() => {
    if (!visible || !scrollRef.current) return
    const pending = messages.flatMap(message => message.tools || []).find(tool => tool.approval?.status === 'pending' && !tool.approval.website_mods?.length && !tool.approval.slippi_review)?.approval.id
    if (pending && shownApproval.current !== pending) {
      shownApproval.current = pending
      scrollRef.current.querySelector('.assistant-approval.is-pending')?.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
    } else if (!pending && !downloadApproval && !slippiApproval && follow.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, pendingInputs, busy, visible])

  const updateAnswer = (id, fn) => setMessages(previous => previous.map(message => message.id === id
    ? { id: message.id, ...fn(message) } : message))
  const toggleSelection = (item) => setSelection(previous => previous.some(s => keyOf(s) === keyOf(item))
    ? previous.filter(s => keyOf(s) !== keyOf(item)) : [...previous, { id: item.id, character: item.character, name: item.name }].slice(0, 100))

  const attachFiles = async values => {
    if (!access.ready || uploading) return
    const uploads = Array.from(values)
    if (attachedFiles.length + uploads.length > 8) { setError('Attach up to eight files per message.'); return }
    setUploading(true)
    try {
      for (const file of uploads) {
        // a ZIP is never unpacked whole (only the chosen model and what it links), so it may be bigger
        const zip = /\.zip$/i.test(file.name)
        if (file.size > (zip ? 1024 : 128) * 1024 * 1024) {
          throw new Error(zip
            ? 'ZIP files must be no larger than 1 GB. Make a smaller ZIP with only the model you want and the textures beside it.'
            : 'Files must be no larger than 128 MB. A model with its textures can be attached as a ZIP of up to 1 GB.')
        }
        const form = new FormData(); form.append('file', file)
        const result = await api.post(`${ROOT}/files`, form)
        setAttachedFiles(previous => [...previous, result.file])
      }
    } catch (err) { setError(err.message) }
    finally { setUploading(false) }
  }

  // A picture from the workbench is already a file of this chat: attach its
  // record as it is (Randall is shown attached pictures as images).
  const attachExisting = file => {
    if (!file?.file_id) return
    if (attachedFiles.some(item => item.file_id === file.file_id)) return
    if (attachedFiles.length >= 8) { setError('Attach up to eight files per message.'); return }
    setAttachedFiles(previous => previous.some(item => item.file_id === file.file_id) ? previous : [...previous, file])
  }
  const acceptsDrop = event => event.dataTransfer.types.includes('Files') || event.dataTransfer.types.includes(PICTURE_DRAG_TYPE)
  const dropOnChat = event => {
    const picture = event.dataTransfer.getData(PICTURE_DRAG_TYPE)
    if (picture) {
      event.preventDefault(); event.stopPropagation()
      try { attachExisting(JSON.parse(picture)) } catch { /* not ours */ }
    } else if (event.dataTransfer.files.length) {
      event.preventDefault(); event.stopPropagation(); attachFiles(event.dataTransfer.files)
    }
  }

  // Only the first message declares the task (backend `recipes.chat_task`) and
  // carries the starting pick (startPick.js says the exact shapes).
  const messageContext = () => outgoingContext({ context, selection, files: attachedFiles, task, locked: taskLocked,
    editor: editorBridge?.editor || null, picker, pick: startPick })

  const enqueue = async (mode = 'queue') => {
    const text = draft.trim()
    if (!text || !chatId || uploading || loadingChat || !access.ready || changingInputRef.current) return
    changingInputRef.current = true; setChangingInput(true); setError('')
    const sentContext = messageContext()
    const fingerprint = JSON.stringify({ chatId, text, mode, context: sentContext })
    if (inputRetry.current?.fingerprint !== fingerprint) inputRetry.current = { fingerprint, id: crypto.randomUUID().replaceAll('-', '') }
    try {
      const result = await api.post(`${ROOT}/chats/${chatId}/inputs`, { id: inputRetry.current.id, message: text, context: sentContext, mode })
      setPendingInputs(result.pending_inputs || [])
      inputRetry.current = null
      setDraft(value => value.trim() === text ? '' : value)
      setAttachedFiles(previous => previous.filter(file => !sentContext.files.some(sent => sent.file_id === file.file_id)))
      try { receiveChat(await api.get(`${ROOT}/chats/${chatId}`)) } catch { /* Accepted input remains visible and durable. */ }
    } catch (err) { setError(err.message) }
    finally { changingInputRef.current = false; setChangingInput(false) }
  }
  const changePending = async (id, changes) => {
    if (changingInputRef.current) return false
    changingInputRef.current = true; setChangingInput(true); setError('')
    try {
      const result = changes ? await api.patch(`${ROOT}/chats/${chatId}/inputs/${id}`, changes)
        : await api.delete(`${ROOT}/chats/${chatId}/inputs/${id}`)
      setPendingInputs(result.pending_inputs || [])
      try { receiveChat(await api.get(`${ROOT}/chats/${chatId}`)) } catch { /* A failed refresh must not discard an accepted Edit. */ }
      return true
    } catch (err) { setError(err.message); return false }
    finally { changingInputRef.current = false; setChangingInput(false) }
  }

  const editPending = async item => {
    if (await changePending(item.id)) {
      setDraft(value => value.trim() ? `${value}\n${item.content}` : item.content)
      setAttachedFiles(previous => [...previous, ...(item.context?.files || []).filter(file => !previous.some(existing => existing.file_id === file.file_id))])
      inputRef.current?.focus()
    }
  }
  const batchPending = async (items, action) => {
    if (changingInputRef.current || !items.length) return
    changingInputRef.current = true; setChangingInput(true); setError('')
    let next = null
    try {
      const result = await api.post(`${ROOT}/chats/${chatId}/inputs/batch`, { ids: items.map(item => item.id), action })
      setPendingInputs(result.pending_inputs || [])
      const snapshot = await api.get(`${ROOT}/chats/${chatId}`)
      receiveChat(snapshot)
      if (action === 'send' && !result.reply_run_id && !snapshot.reply_run_id && snapshot.pending_inputs.length) {
        next = { item: snapshot.pending_inputs[0], snapshot }
      }
    } catch (err) { setError(err.message) }
    finally { changingInputRef.current = false; setChangingInput(false) }
    if (next) setResumeInput(next)
  }

  // What `sendGate` reads of the panel now (the refs as they are at the call, not at the render).
  const sendState = () => ({ uploading, loadingChat, ready: access.ready, changingInput: changingInputRef.current,
    busy: busyRef.current, replying: Boolean(replyRunId || controller.current) })
  // `typed`: the text is the message bar's draft (cleared on send, put back if it fails); a queued message is not.
  const send = async (text = draft, queued = null, snapshot = null) => {
    const typed = !queued
    text = text.trim()
    const way = sendGate({ ...sendState(), text, queued })
    if (way === 'queue') return enqueue()
    if (way !== 'send') return
    busyRef.current = true; setBusy(true); setError(''); follow.current = true
    const previous = snapshot?.messages || messages
    const sentContext = queued?.context || messageContext()
    let answerId = crypto.randomUUID()
    streamingMessage.current = answerId
    const updateStreamAnswer = fn => updateAnswer(answerId, fn)
    setMessages([...previous, { ...(queued ? { id: queued.id, input_kind: queued.mode } : {}), role: 'user', content: text, context: sentContext },
      { id: answerId, role: 'assistant', content: '', tools: [], status: 'running', run_kind: 'reply' }])
    if (typed) setDraft('')
    const abort = new AbortController(); controller.current = abort
    // The run id is ours from the start: a Stop before the backend's `started` event still names this run, so a
    // turn the backend accepted (or is about to) is stopped there too, not left running unseen.
    const ownRunId = crypto.randomUUID().replace(/-/g, ''); setRunId(ownRunId)
    let acceptedId = null
    try {
      // Recheck immediately before each turn, so sign-out, revoked access and
      // spending by Tracker cannot leave this panel using a stale cached key.
      const token = getPatreonToken()
      const currentEntitlement = await refreshEntitlement()
      if (abort.signal.aborted) throw new DOMException('Stopped', 'AbortError')
      if (token !== getPatreonToken()) throw new Error('Patreon account changed. Please send again.')
      const currentAccess = assistantAccess(status, currentEntitlement)
      if (!currentAccess.ready) throw new Error(currentAccess.label)
      const accountToken = account?.id ? await getAccessToken(account.id) : null
      const response = await authenticatedFetch(api.url(`${ROOT}/chat`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ chat_id: chatId, message: text, context: sentContext,
          game_settings: { vanillaIsoPath: localStorage.getItem('vanilla_iso_path') || '',
            slippiDolphinPath: localStorage.getItem('slippi_dolphin_path') || '' },
          run_id: ownRunId,
          ...(queued ? { input_id: queued.id } : {}),
          ...(accountToken ? { account_token: accountToken } : {}),
          ...(currentAccess.key ? { api_key: currentAccess.key } : {}) }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.error || `Request failed (${response.status})`)
      }
      await readAssistantStream(response, event => {
        if (event.type === 'started') {
          acceptedId = event.chat_id; setChatId(event.chat_id); remember(event.chat_id); setRunId(event.run_id)
          setReplyRunId(event.run_id); setRecovering(true)
          if (queued) setPendingInputs(previous => previous.filter(item => item.id !== queued.id))
          else setAttachedFiles(previous => previous.filter(file => !sentContext.files.some(sent => sent.file_id === file.file_id)))
          if (event.message_id) {
            updateStreamAnswer(message => ({ ...message, id: event.message_id }))
            answerId = event.message_id; streamingMessage.current = answerId
          }
        } else if (event.type === 'input_applied') {
          setMessages(previous => applyPendingInput(previous, event))
          answerId = event.message.id; streamingMessage.current = answerId
          setPendingInputs(event.pending_inputs || [])
        } else if (event.type === 'inputs_changed') {
          setPendingInputs(event.pending_inputs || [])
        } else if (event.type === 'turn_done') {
          updateAnswer(event.message.id, () => event.message)
        } else if (event.type === 'turn_progress') {
          updateAnswer(event.message_id, message => applyTurnProgress(message, event))
        } else if (event.type === 'delta') {
          updateStreamAnswer(message => ({ ...message, content: message.content + event.content }))
        } else if (event.type === 'tool_start') {
          updateStreamAnswer(message => ({ ...message, tools: [...message.tools, event.tool] }))
        } else if (['tool_result', 'approval_requested', 'approval_update'].includes(event.type)) {
          updateStreamAnswer(message => ({ ...message, tools: message.tools.map(t => t.id === event.tool.id ? event.tool : t) }))
          if (event.tool.result?.action_id || event.tool.result?.vault_changed) onRefresh()
          publishSkinCheckpoint(event.tool.result)
          notifyProjectChanges([event.tool])
        } else if (event.type === 'done') {
          updateStreamAnswer(() => event.message)
        }
      })
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
      // Put the text back only into the empty bar send left: a newer draft typed meanwhile wins.
      if (!acceptedId) { setMessages(previous); if (typed) setDraft(current => restoreFailedDraft(current, text)) }
    } finally {
      controller.current = null; streamingMessage.current = null
      let active = false
      if (acceptedId) {
        try {
          const data = await api.get(`${ROOT}/chats/${acceptedId}`)
          receiveChat(data); active = Boolean(data.active_run_id)
        } catch { /* Keep the streamed transcript when offline. */ }
      }
      busyRef.current = active; setBusy(active)
      if (!active) { setRunId(null); setReplyRunId(null) }
      refreshChats().catch(() => {})
      refreshEntitlement()
    }
  }

  useEffect(() => {
    // Ozone's Send now degrades to a normal send when it races turn completion.
    // Let the old SSE finish before opening its replacement, keeping the snapshot.
    if (resumeInput && !replyRunId && !controller.current) {
      setResumeInput(null)
      send(resumeInput.item.content, resumeInput.item, resumeInput.snapshot)
    }
  }, [resumeInput, replyRunId, busy])

  const stop = async () => {
    try { if (runId) await api.post(`${ROOT}/runs/${runId}/cancel`, {}) }
    catch (err) { setError(err.message) }
    controller.current?.abort()
  }
  const downloadMod = async (mod, fileId, items) => {
    if (downloadRef.current || activeDownload || loadingChat) return
    const wasBusy = busyRef.current
    downloadRef.current = true; setDownloadBusy(true)
    busyRef.current = true; setBusy(true); setError(''); follow.current = false; setDirectDownload(mod?.post_id || null)
    let accepted = false
    try {
      const data = await api.post(`${ROOT}/website/download`, { chat_id: chatId, ...(items ? { items } : { post_id: mod.post_id, ...(fileId ? { file_id: fileId } : {}) }) })
      accepted = true
      setChatId(data.chat_id); remember(data.chat_id); setRecovering(true)
      const chat = await api.get(`${ROOT}/chats/${data.chat_id}`)
      receiveChat(chat)
    } catch (err) {
      setError(err.message)
      if (!accepted) { setDownloadBusy(false); downloadRef.current = false; setBusy(wasBusy); busyRef.current = wasBusy; setDirectDownload(null) }
    }
  }
  const decideApproval = async (approvalId, decision, choice) => {
    const data = await api.post(`${ROOT}/chats/${chatId}/approvals/${approvalId}`, { decision, ...(choice ? { choice } : {}) })
    setDirectDownload(null)
    // SSE/polling can already be newer than the POST response. Only replace a
    // still-pending approval; never overwrite a completed receipt with old data.
    setMessages(previous => previous.map(message => ({ ...message, tools: message.tools?.map(tool =>
      tool.approval?.id === approvalId && tool.approval.status === 'pending' ? data.tool : tool) })))
  }
  const undo = async (actionId) => {
    setError('')
    try {
      await api.post(`${ROOT}/actions/${actionId}/undo`, {})
      setMessages(previous => previous.map(m => ({ ...m, tools: m.tools?.map(t =>
        t.result?.action_id === actionId ? { ...t, result: { ...t.result, undone: true } } : t) })))
      await onRefresh()
    } catch (err) { setError(err.message) }
  }
  // `nextTask`/`nextDraft` come only from a starting point (a sidebar row, "Start
  // another", a mismatch nudge); the + button starts a plain Ask chat.
  const newChat = (nextTask = null, nextDraft = '') => {
    if (busyRef.current || uploading || changingInputRef.current) return
    ++loadVersion.current; setLoadingChat(false); setChatId(null); remember(null)
    setMessages([]); setSelection([]); setAttachedFiles([]); setError(''); setDraft(nextDraft); setTask(nextTask); setShowHistory(false); setShowSettings(false)
    setStartPick(null)
    setPendingInputs([]); setReplyRunId(null); setResumeInput(null); inputRetry.current = null
    inputRef.current?.focus()
  }
  const deleteChat = async chat => {
    if (!chat?.id || busyRef.current || deletingChat || changingInputRef.current) return
    setDeletingChat(chat.id)
    try {
      await api.delete(`${ROOT}/chats/${chat.id}`)
      setChats(previous => previous.filter(item => item.id !== chat.id))
      if (chat.id === chatId) { newChat(); setShowHistory(true) }
      await refreshChats()
    }
    catch (err) { setError(err.message) }
    finally { setDeletingChat(null) }
  }

  // The one delivery follow-up that IS an application endpoint today: re-read
  // the Launcher's selection for the designated destination.
  const recheckActivation = async () => {
    try {
      const context = await api.get(`${ROOT}/app-context`)
      const id = context?.destination?.destination_id
      if (!id) { setError('No game copy is set as yours yet.'); return }
      await api.post(`${ROOT}/destination/${id}/activation`, {})
    } catch (err) { setError(err.data?.error || err.message) }
  }

  // A starting point (a chip, the pill's menu) declares the task; the composer then
  // offers its pick ("Choose costume") without opening anything, and focus goes to
  // the message box: the pick is optional and words work too.
  const pickTask = id => {
    setTask(id); setStartPick(null)
    inputRef.current?.focus()
  }
  // A picked costume or stage is THE starting selection (startPick.outgoingContext),
  // so skins attached before the pick are dropped here, in sight, not at send time.
  const choosePick = pick => { setStartPick(pick); if (pick && pick.kind !== 'fighter') setSelection([]); requestAnimationFrame(() => inputRef.current?.focus()) }
  // The starting points again as sidebar rows: each starts a new chat in the state
  // its chip gives. One that is not built yet is left out: a disabled row reads
  // poorly at sidebar width.
  const startRows = startable.map(item => ({ id: item.id, label: item.label, title: item.hint,
    icon: <TaskIcon task={item} size={16} />, onSelect: () => newChat(item.id) }))

  const openUrl = url => {
    if (window.electron?.openExternal) window.electron.openExternal(url)
    else window.open(url, '_blank', 'noopener,noreferrer')
  }
  const linkPatreon = () => openUrl(buildPatreonAuthorizeUrl())


  return <ChatLayout className="nucleus-assistant" active={visible} sidebarOpen={showHistory} aria-label="Randall"
    onKeyDown={event => { if (event.key === 'Escape') { if (showSettings) closeSettings(); else setShowHistory(false) } }}
    sidebar={<ChatSidebar sidebarOpen={showHistory} onToggleSidebar={() => setShowHistory(value => !value)} id="nucleus-chat-history" chats={chats} activeId={chatId} onSelect={openChat} onNew={() => newChat()} onDelete={deleteChat}
      nav={startRows} badgeFor={chat => labelFor(startable, chat.task)} statusFor={chat => chat.id === chatId ? openChatStatus : null}
      disabled={busy || uploading || changingInput || Boolean(deletingChat)}
      footer={<>
        <ChatAccount entitlement={entitlement} onSettings={openSettings} />
      </>} />}>
      <div className="coach-page" onDragOver={event => { if (acceptsDrop(event)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' } }}
        onDrop={dropOnChat}>
        <ChatHeader actions={<ReportChatButton conversationId={chatId} messageCount={messages.length}
          busy={busy || loadingChat} onClick={() => setReporting(true)} />} />
        {visible && reporting && <ChatReportModal show onClose={() => setReporting(false)} surface="mods"
          conversationId={chatId} budget={budgetFromEntitlement(entitlement)} />}
        {visible && downloadApproval && <DownloadApprovalDialog key={downloadApproval.id} approval={downloadApproval} chatId={chatId} onDecision={decideApproval} />}
        {visible && slippiApproval && <SlippiApprovalDialog key={slippiApproval.id} approval={slippiApproval}
          mod={[...websiteCards.values()].find(card => slippiApproval.post_id ? card.mod.post_id === slippiApproval.post_id : card.mod.title === slippiApproval.mod_title)?.mod}
          onDecision={decideApproval} />}
        {showSettings && <section className="assistant-settings" aria-label="Randall settings panel">
          <div className="assistant-settings-card">
            <div className="assistant-settings-head"><h2>Randall settings</h2><button ref={settingsClose} className="assistant-icon-button" aria-label="Close Randall settings" onClick={closeSettings}><Icon name="close" /></button></div>
            <div className="assistant-settings-row"><span className="assistant-sidebar-label">Model</span><strong>{modelLabel}</strong><p>Used for answering, explaining and running the tools.</p></div>
            <div className="assistant-settings-row"><span className="assistant-sidebar-label">Randall access</span><strong>{access.label}</strong>
              <p>Your Patreon tier sets your monthly Randall usage. Setup checks and browsing don’t count.</p>
              <div className="assistant-settings-actions"><button className="assistant-secondary" onClick={openPatreon}>Patreon settings</button>{entitlement?.linked && !entitlement?.active && <button className="assistant-secondary" title="Link Patreon again to refresh your membership" onClick={linkPatreon}>Re-link Patreon</button>}<button className="assistant-secondary" onClick={() => { refreshStatus(); refreshEntitlement() }}>Check again</button></div></div>
            <UsageRow entitlement={entitlement} />
            <div className="assistant-settings-row"><span className="assistant-sidebar-label">Developer details</span>
              <label className="assistant-settings-switch"><input type="checkbox" role="switch" checked={devDetails}
                onChange={event => setDevDetails(event.target.checked)} /><strong>{devDetails ? 'Shown' : 'Hidden'}</strong></label>
              <p>Show how each step was decided: the questions Randall asked its model, measured values and the
                working pictures behind every decision. Useful when building Nucleus; most people leave it off.</p></div>
          </div>
        </section>}
        <div className="coach-scroll" ref={scrollRef} onScroll={event => {
          const el = event.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90
        }}>
          {/* An empty chat has nothing here: its greeting and starting points sit
              around the composer, in the middle of the page (Composer `start`). */}
          {loadingChat ? <div className="app-panel-loading" role="status"><HexagonLoader size={72} decorative /><p>Loading conversation…</p></div>
            : messages.map((message, index) => <Fragment key={message.id || index}><article className={`coach-turn coach-turn--${message.role}`}>
            {message.role === 'assistant' && <RandallIdentity />}
            {message.role === 'user' && message.input_kind === 'steer' && <div className="steered-tag">↳ steered</div>}
            {message.role === 'user' && contextNotes(message.context).map(note => <small key={note} className="randall-sent-note">{note}</small>)}
            {message.role === 'user' && message.context?.files?.length > 0 && <ModFileCards files={message.context.files} />}
            {orderedMessageParts(message).map(part => part.kind === 'text'
              ? <SmoothText key={part.key} text={message.role === 'assistant' ? visibleAssistantText(part.text) : part.text} active={!part.complete && message.role === 'assistant' && message.status === 'running'}
                  onReveal={() => { if (follow.current && !awaitingApproval && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight }}>
                  {text => text.trim() && <div className={`coach-msg coach-md coach-msg--${message.role}`}><Markdown>{text}</Markdown></div>}
                </SmoothText>
              : groupFileReads(part.tools).map(group => group[0].name === 'search_docs'
              ? <FileReadActivity key={group[0].id} tools={group} renderExcerpt={text => <Markdown>{text}</Markdown>} />
              : ['search_vault', 'inspect_mod'].includes(group[0].name)
              ? <VaultReadActivity key={group[0].id} tools={group} />
              : group.length > 1 || INTERMEDIATE_TOOLS.has(group[0].name)
              ? <ModelWorkActivity key={group[0].id} tools={group} />
              : <ToolCard key={group[0].id} tool={group[0]} selection={selection}
                  chatId={chatId} visible={visible} liveGameTool={liveGameTool} gameInPanel={gameInPanel} studio={studio}
              toggleSelection={toggleSelection} onOpenVault={onOpenVault} onOpenProject={onOpenProject} onUndo={undo} onDecision={decideApproval}
              cards={[...websiteCards.values()].filter(card => card.owner === group[0].id)} account={account}
              onAsk={text => { setDraft(text); inputRef.current?.focus() }}
              onActivation={recheckActivation}
              onDownload={downloadMod} onDownloadMany={mods => downloadMod(null, null, mods.map(mod => ({ post_id: mod.post_id })))} downloadBusy={activeDownload || loadingChat} directDownload={directDownload}
              busy={busy || loadingChat || !access.ready} />))}
            {message.error && <p className="assistant-error" role="alert">{message.error}</p>}
            {/* Same hover row the Tracker side already had; copies the reply text
                only, not the tool activity interleaved with it. */}
            {message.role === 'assistant' && message.status !== 'running' && !message.error
              && visibleAssistantText(message.content || '').trim() && <div className="coach-msg-actions">
              <CopyButton text={visibleAssistantText(message.content || '')} />
            </div>}
            {showWorkingBubble(message) && <TypingBubble />}
            {['cancelled', 'interrupted'].includes(message.status) && <p className="assistant-muted">{message.status === 'cancelled' ? 'Stopped' : 'Interrupted'} · Completed tool results are kept.</p>}
          </article>
          {/* Task follow-ups sit beside the last reply, not inside it, so the
              avatar stays level with the bubble. */}
          {index === messages.length - 1 && message.role === 'assistant' && message.status !== 'running' && (() => {
            const mismatch = mismatchOf(message), mismatchLabel = mismatch && labelFor(startable, mismatch.family)
            return <>
              {mismatchLabel && <TaskMismatch label={mismatchLabel} disabled={busy || uploading || changingInput}
                onStart={() => newChat(mismatch.family, previousUserText(messages, index))} />}
              {startable.length > 0 && showStartAnother(task, messages, busy) && <StartAnother tasks={startable}
                disabled={uploading || changingInput} onPick={id => newChat(id)}
                followUp={followUpFor(task, terminalReceipt(task, message))} onFollowUp={text => { setDraft(text); inputRef.current?.focus() }} />}
            </>
          })()}
          </Fragment>)}
          <QueuedPrompts items={pendingInputs.filter(item => !replyRunId || item.mode !== 'steer')} running={Boolean(replyRunId)} disabled={changingInput || uploading || loadingChat || !access.ready}
            onEdit={editPending} onRemove={id => changePending(id)} onClear={() => batchPending(pendingInputs, 'clear')}
            onSend={items => batchPending(items, 'send')} />
        </div>
        <Composer start={startScreen} tasks={tasks} ready={statusSettled} starters={STARTERS}
          task={task} locked={taskLocked} picker={picker} pick={startPick}
          pickSources={{ metadata: vaultMetadata, fighters: picker === 'fighter' ? importFighters : undefined,
            stages: picker === 'stage' ? status?.recolor_stages : undefined }}
          busy={busy} pillDisabled={!access.ready || loadingChat} pickDisabled={busy || loadingChat}
          onTask={pickTask} onPick={choosePick} onClearPick={() => setStartPick(null)}
          onStarter={prompt => { setTask(null); setDraft(prompt); inputRef.current?.focus() }}
          onSubmit={() => send()} nowrapPlaceholder={Boolean(taskPlaceholder)}
          onDragOver={event => {
            if (acceptsDrop(event)) { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy' }
          }} onDrop={dropOnChat}
          attach={<button type="button" className="ozone-lead" aria-label="Attach mod files"
            title={uploading ? 'Uploading attachments...' : 'Attach mod files or drop them on the message bar'}
            disabled={!access.ready || uploading} onClick={() => fileInput.current?.click()}>
            {uploading
              ? <svg className="ozone-lead-spin" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="42 14"/></svg>
              : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>}
          </button>}
          input={{ inputRef, value: draft, onChange: setDraft, onSend: () => send(), maxLength: 8000, busy, onStop: stop,
            onQueue: () => enqueue(),
            disabled: !access.ready, sendDisabled: !access.ready || loadingChat || uploading || changingInput || (busy && !chatId),
            placeholder: access.ready ? taskPlaceholder || 'Message Randall...' : entitlement === null ? 'Checking Patreon...'
              : entitlement?.linked || entitlement?.checkFailed ? access.label : 'Link Patreon to chat with Randall',
            lockedAction: !access.ready && access.joinFree ? <JoinFreeUnlock onJoin={() => openUrl(PATREON_CAMPAIGN_URL)} onCheck={refreshEntitlement} />
              : !access.ready && entitlement !== null ? <button type="button" className="chat-unlock"
              onClick={entitlement?.checkFailed || access.usedUp || access.paused ? refreshEntitlement : entitlement?.linked ? openPatreon : linkPatreon}>
              {entitlement?.checkFailed ? 'Try again' : access.usedUp || access.paused ? 'Check again' : entitlement?.linked ? 'Patreon' : 'Link Patreon'}</button> : null }}>
          <LongRunningNotice message={messages.findLast(message => message.role === 'assistant'
            && message.run_kind !== 'download' && message.status === 'running')} onStop={stop} />
          {lowUsage && <p className="assistant-low-usage" role="status">{lowUsage.text} {lowUsage.refill}</p>}
          {error && <div className="assistant-error" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
          {/* A picked costume or stage replaces attached skins (choosePick clears them), so this chip and the pick never show the same thing. */}
          {selection.length > 0 && <div className="assistant-context"><button onClick={() => setSelection([])} title="Clear attached skins">{selection.length} skin{selection.length === 1 ? '' : 's'} attached{(picker === 'costume' || picker === 'stage') && startPick && !taskLocked ? ` (not used: starting from the picked ${picker})` : ''} ×</button></div>}
          {editorBridge?.editor && <div className="assistant-editor-context"><span>Editing {editorBridge.editor.name}
            {editorBridge.editor.texture ? ` · ${editorBridge.editor.texture.name}` : ''}</span>
            <button type="button" aria-label="Close Randall sidebar" onClick={editorBridge.hideSidebar}>×</button></div>}
          {attachedFiles.length > 0 && <div className="assistant-file-attachments">{attachedFiles.map(file => <button key={file.file_id}
            type="button" title="Remove attachment" onClick={() => setAttachedFiles(previous => previous.filter(item => item.file_id !== file.file_id))}>{file.name} ×</button>)}</div>}
          <input ref={fileInput} type="file" hidden multiple accept=".dat,.usd,.zip,.png,.glb,.gltf,.fbx,.obj,.smd,.dae,.anim,.aj,.lat,.rat,.pat,.sat,.mat,.cat,.fat,.wat"
            onChange={event => { attachFiles(event.target.files); event.target.value = '' }} />
        </Composer>
      </div>
      {!inEditor && <WorkbenchPanel state={workbench} visible={visible} open={workbenchOpen} onOpenChange={setWorkbenchOpen}
        gameTool={gameTool} chatId={chatId} onAttach={attachExisting} />}
  </ChatLayout>
}
