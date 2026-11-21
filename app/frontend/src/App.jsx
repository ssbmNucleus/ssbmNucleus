import { lazy, Suspense, useState, useEffect, useCallback, useRef } from 'react'
import DownloadModal from './vault/import/DownloadModal'
import HexagonLoader from './shared/ui/HexagonLoader'
import AppDialogHost from './shared/ui/AppDialogHost'
import BackendStoppedScreen from './shared/ui/BackendStoppedScreen'
import InterruptedJobsNotice from './shared/jobs/InterruptedJobsNotice'
import BrandWordmark from './shared/ui/BrandWordmark'
import DebugTierToggle from './settings/DebugTierToggle'
import { RECORD_MODE } from './shared/config/recordMode'
import { NucleomeTabs } from './tracker/NucleomeTabs'
import { NUCLEOME_ENABLED, COMBO_VIDEO_ENABLED, RANDALL_ENABLED } from './shared/config/features'
import { ASSISTANT_ENABLED } from './shared/config/features'
import { EditorContext } from './shared/lib/EditorContext'
import { useDownloadQueue, DOWNLOAD_PHASES } from './vault/import/useDownloadQueue'
import { useUpdateStatus } from './settings/useUpdateStatus'
import { playSound, playHoverSound } from './shared/audio/sounds'
import { api } from './shared/transport/api'
import { createMetadataRefresh } from './vault/metadataRefresh'
import { VaultActiveContext } from './vault/vaultActive'
import { resolveStageNavigation } from './randall/assistant/stageNavigation'
import { setPatreonToken, getPatreonToken, getEntitlement, ENTITLEMENT_EVENT } from './shared/account/entitlement'
import { IGNORED_LINK_MESSAGE, decidePatreonLink } from './shared/account/patreonLinkGuard'
import { confirmImportLink } from './vault/import/importLinkPrompt'
import { appAlert } from './shared/ui/appDialogs'
import { clearSignOutPending, signOutPending } from './shared/account/signOutPending'
import { createVaultTokenMirror } from './tracker/cloud/vaultTokenMirror'
import { createMcpAccountMirror, createMcpConfirmWatcher, createMcpWindowMirror, SLIPPI_PATH_EVENT } from './randall/assistant/mcpAccount'
import McpImportChip from './randall/assistant/McpImportChip'
import { useMcpImportSaved, useMcpVaultChanged } from './randall/assistant/mcpImport'
import { appConfirm } from './shared/ui/appDialogs'
import { subscribe as subscribeSocket } from './shared/transport/socket'
import { version as APP_VERSION } from '../package.json'
import './App.css'
import './shared/ui/buttons.css'
import './shared/ui/modals.css'

// Split the large application surfaces into independent modules. Nucleus tabs
// mount on first visit and then stay mounted, so unopened surfaces do not fetch
// or initialize during startup while visited tabs retain state/background work.
const StorageViewer = lazy(() => import('./vault/StorageViewer'))
const MexPanel = lazy(() => import('./projects/MexPanel'))
const Settings = lazy(() => import('./settings/Settings'))
const UploadPage = lazy(() => import('./upload/UploadPage'))
const FirstRunSetup = lazy(() => import('./setup/FirstRunSetup'))
const NucleomeApp = lazy(() => import('./tracker/NucleomeApp'))
// The assistant ships only in preview builds. A ternary on the constant
// ASSISTANT_ENABLED lets Rollup fold the dynamic import away, so a stable
// build carries no AssistantPanel chunk at all (tools/build/ship_guard.py
// checks dist for it). Every use below sits behind ASSISTANT_ENABLED.
const loadAssistantPanel = ASSISTANT_ENABLED
  ? () => import('./randall/assistant/AssistantPanel')
  : null
const AssistantPanel = ASSISTANT_ENABLED ? lazy(loadAssistantPanel) : null

function PanelLoading({ children }) {
  return (
    <div className="app-panel-loading">
      <HexagonLoader size={72} decorative />
      <p>{children}</p>
    </div>
  )
}

// "Don't show again" for the setup-health notice stores the exact set of
// problem ids it was dismissed for — a new, different problem still notifies.
const SETUP_NOTICE_HIDDEN_KEY = 'setup_health_hidden_problems'

const setupProblemSignature = (problems) =>
  problems.map((problem) => problem.id).sort().join(',')

// nucleus <-> nucleOME mode shell. Both keys persist across launches so
// switching modes and back returns you to where you were.
const MODE_STORAGE_KEY = 'nucleus_app_mode'
const NUCLEOME_TAB_KEY = 'nucleome_active_tab'

// NUCLEOME_ENABLED (shared/config/features.js) shipped true in 0.7.0; the guard
// stays so a future build that gates Tracker off again can never restore a
// stored 'nucleome' mode.
const readStoredMode = () =>
  NUCLEOME_ENABLED && localStorage.getItem(MODE_STORAGE_KEY) === 'nucleome'
    ? 'nucleome'
    : 'nucleus'

function App() {
  const [activeTab, setActiveTab] = useState('storage');
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantMounted, setAssistantMounted] = useState(false)
  const [vaultNavigation, setVaultNavigation] = useState(null)
  const [vaultContext, setVaultContext] = useState({})
  const [assistantEditor, setAssistantEditor] = useState(null)
  const [textureRequest, setTextureRequest] = useState(null)
  const [editorSidebar, setEditorSidebar] = useState(false)
  const editorCloseHandler = useRef(null)
  const editorNavigation = useRef(false)
  const navigateFromAssistant = async action => {
    if (editorNavigation.current) return
    editorNavigation.current = true
    try {
      if (assistantEditor && (!editorCloseHandler.current || !await editorCloseHandler.current())) return
      await action()
    } finally { editorNavigation.current = false }
  }
  const openAssistantEditor = item => {
    if (item.kind === 'stage' || item.stageCode) return openAssistantStage(item, true)
    if (assistantEditor?.skinId === item.id && assistantEditor?.character === item.character) { setEditorSidebar(true); return }
    return navigateFromAssistant(() => {
      setAssistantEditor({ character: item.character, skinId: item.id, name: item.name })
      setTextureRequest(null); setEditorSidebar(true)
      setVaultNavigation({ character: item.character, skinId: item.id, editor: true })
      setActiveTab('storage'); setAssistantMounted(true); setAssistantOpen(true)
    })
  }
  const openAssistantStage = (item, editor = false) => navigateFromAssistant(async () => {
    const [catalog, variants] = await Promise.all([api.get('/stages/catalog'), api.get('/das/storage/variants')])
    const target = resolveStageNavigation(item, catalog.stages || [], variants.variants || [])
    setVaultNavigation({ kind: 'stage', ...target, editor })
    setActiveTab('storage')
    setAssistantOpen(editor)
    if (editor) setAssistantMounted(true)
  })
  const closeAssistantEditor = useCallback(() => {
    setAssistantEditor(null); setTextureRequest(null); setEditorSidebar(false)
  }, [])
  const setEditorTexture = useCallback(texture => {
    setAssistantEditor(previous => previous ? { ...previous, texture } : previous)
  }, [])
  // Randall's latest working copy of a costume, so an open editor can follow
  // its edits instead of the user closing it and clicking Edit on a new card.
  const [assistantCheckpoint, setAssistantCheckpoint] = useState(null)
  const publishCheckpoint = useCallback(checkpoint => {
    setAssistantCheckpoint(previous => (
      previous && previous.target?.skin_id === checkpoint.target?.skin_id
      && previous.sessionId === checkpoint.sessionId
      && previous.revision >= checkpoint.revision ? previous : checkpoint))
  }, [])
  const [visitedNucleusTabs, setVisitedNucleusTabs] = useState(
    () => new Set(['storage'])
  )

  // The active panel mounts in the same render that selects it; recording the
  // visit keeps it mounted (but hidden) on later tab and mode transitions.
  useEffect(() => {
    setVisitedNucleusTabs((visited) => {
      if (visited.has(activeTab)) return visited
      const next = new Set(visited)
      next.add(activeTab)
      return next
    })
  }, [activeTab])

  const shouldMountNucleusTab = (tab) =>
    tab === activeTab || visitedNucleusTabs.has(tab)

  // App mode: 'nucleus' = the shipping modding app (untouched), 'nucleome' =
  // the replay-analysis sibling app (shell only for now). The header brand
  // block is the toggle; the accent tokens follow via data-mode on <html>.
  const [mode, setMode] = useState(readStoredMode);
  const [nucleomeTab, setNucleomeTab] = useState(() => {
    const stored = localStorage.getItem(NUCLEOME_TAB_KEY)
    // 'home' was replaced by 'combos'; migrate stale stored values. A stored
    // 'combovideo' or 'coach' tab must not restore in builds where that
    // feature is gated off (unreleased), or it lands on a page that 404s.
    if (!stored || stored === 'home') return 'combos'
    if (stored === 'combovideo' && !COMBO_VIDEO_ENABLED) return 'combos'
    if (stored === 'coach' && !RANDALL_ENABLED) return 'combos'
    if (stored === 'friends') return 'combos' // Friends was removed in 0.8.16
    return stored
  });

  // Fetch the assistant's code once the app has settled, so the first click on
  // AI doesn't flash the lazy-load fallback. (Hovering the tab also starts it.)
  useEffect(() => {
    if (!ASSISTANT_ENABLED) return undefined
    const timer = setTimeout(() => { loadAssistantPanel().catch(() => {}) }, 3000)
    return () => clearTimeout(timer)
  }, [])

  // Restore the persisted mode's theming on launch (no flood delay on boot).
  useEffect(() => {
    document.documentElement.setAttribute('data-mode', readStoredMode())
  }, [])

  // Re-entry animation for the (kept-mounted) nucleus content: display:none
  // toggles can't animate, so a short-lived class replays the entrance.
  const [nucleusEntering, setNucleusEntering] = useState(false)

  // nucleOME mounts on first open and then STAYS mounted (hidden) across
  // mode toggles, so in-flight work — a streaming coach turn especially —
  // survives a trip to Nucleus mode. Nucleus-only sessions never mount it.
  const [nucleomeMounted, setNucleomeMounted] = useState(mode === 'nucleome')
  useEffect(() => {
    if (mode === 'nucleome') setNucleomeMounted(true)
  }, [mode])

  const toggleMode = () => {
    if (!NUCLEOME_ENABLED) return
    const next = mode === 'nucleus' ? 'nucleome' : 'nucleus'
    playSound('start')
    setMode(next)
    localStorage.setItem(MODE_STORAGE_KEY, next)
    if (next === 'nucleus') {
      setNucleusEntering(true)
      setTimeout(() => setNucleusEntering(false), 450)
    }
    // The accent flood trails the suffix morph slightly so the recolor feels
    // like it propagates outward from the wordmark.
    setTimeout(() => document.documentElement.setAttribute('data-mode', next), 150)
  }

  const handleNucleomeTab = (tab) => {
    if (tab === nucleomeTab) return
    playSound('boop')
    setNucleomeTab(tab)
    localStorage.setItem(NUCLEOME_TAB_KEY, tab)
  }
  const [metadata, setMetadata] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchMetadata] = useState(() => createMetadataRefresh({
    read: () => api.get('/storage/metadata'), setMetadata, setLoading,
  }));
  // A model import the user's own AI ran over MCP saved a costume: read the vault again, as after Randall's own
  // import (AssistantPanel's onRefresh). Mounted here, not in the header chip, so a hidden header misses none.
  useMcpImportSaved(fetchMetadata);
  // Any other tool it ran that saved to the vault (a Stage Lab save, a download): the backend says so on the socket.
  useMcpVaultChanged(fetchMetadata);
  // True only while the fullscreen skin *editor* is up. The skin creator's
  // select step ("New Costume" picker) is NOT fullscreen — it renders below the
  // app header like a normal vault page, so the header stays visible for it.
  const [skinCreatorFullscreen, setSkinCreatorFullscreen] = useState(false);
  const [showFirstRunSetup, setShowFirstRunSetup] = useState(false);
  const [settingsRefreshVersion, setSettingsRefreshVersion] = useState(0);

  // Community account (shared with ssbmnucleus.net). Upload is gated on it —
  // or on the Discord sign-in, which is an account on the same website
  // project (the backend publishes with that session instead).
  const [account, setAccount] = useState(null);
  const [discordAccount, setDiscordAccount] = useState(null);
  const uploadAccount = account || discordAccount;
  const [showUploadLock, setShowUploadLock] = useState(false);

  useEffect(() => {
    let cancelled = false
    let unsubscribe = () => {}

    // Account support brings in Supabase, so load it as a separate module
    // instead of making every renderer parse the client in the entry chunk.
    import('./shared/account/account').then(({ getAccount, onAccountChange }) => {
      if (cancelled) return
      getAccount().then((next) => {
        if (!cancelled) setAccount(next)
      }).catch(() => {})
      unsubscribe = onAccountChange((next) => {
        if (!cancelled) setAccount(next)
      })
    }).catch(() => {})

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])

  // The Discord half: mirrored from the backend, re-read whenever the
  // window regains focus (the OAuth hop happens in the browser) or the
  // Settings Discord row reports a change.
  useEffect(() => {
    if (!NUCLEOME_ENABLED) return undefined
    let cancelled = false
    const refresh = () => api.get('/api/account/discord')
      .then((d) => { if (!cancelled) setDiscordAccount(d?.account ? {
        id: d.account.user_id, username: d.account.username || 'Discord user',
        avatarUrl: d.account.avatar_url, source: 'discord',
      } : null) })
      .catch(() => {})
    refresh()
    window.addEventListener('focus', refresh)
    window.addEventListener('discord-account-changed', refresh)
    return () => {
      cancelled = true
      window.removeEventListener('focus', refresh)
      window.removeEventListener('discord-account-changed', refresh)
    }
  }, [])

  // Signing in clears the lock popover; signing out while on Upload bounces
  // back to the vault (the tab is locked again).
  useEffect(() => {
    if (uploadAccount) setShowUploadLock(false)
    else if (activeTab === 'upload') setActiveTab('storage')
  }, [uploadAccount, activeTab])

  // The lock popover dismisses on outside click or Escape.
  useEffect(() => {
    if (!showUploadLock) return
    const onPointerDown = (event) => {
      if (!event.target.closest?.('.upload-tab-anchor')) setShowUploadLock(false)
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setShowUploadLock(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [showUploadLock])

  // First-run setup state
  const [setupNeeded, setSetupNeeded] = useState(null); // null = checking, true = needed, false = complete

  // Boot-time setup health notice. Catches problems /setup/status can't see —
  // the saved vanilla ISO path lives in this profile's localStorage — so the
  // user gets a "re-run setup" nudge instead of a surprise ISO picker later.
  const [setupProblems, setSetupProblems] = useState([]);
  const [setupNoticeHidden, setSetupNoticeHidden] = useState(true);

  // Publish the header's real height as --app-header-h. The header stacks
  // ABOVE in-tree modal overlays (.app-content is a stacking context below
  // it), so overlays start below the header and modal height caps subtract
  // it — measured, so it tracks zoom/resize and the fullscreen-creator case
  // where the header unmounts entirely.
  const headerObserverRef = useRef(null)
  const headerRef = useCallback((el) => {
    headerObserverRef.current?.disconnect()
    headerObserverRef.current = null
    const root = document.documentElement
    if (!el) {
      root.style.setProperty('--app-header-h', '0px')
      return
    }
    const apply = () => root.style.setProperty('--app-header-h', `${el.offsetHeight}px`)
    apply()
    headerObserverRef.current = new ResizeObserver(apply)
    headerObserverRef.current.observe(el)
  }, [])

  // Version shown in the header. The authoritative value is the packaged
  // Electron app version (app.getVersion(), driven by the root package.json
  // the build uses) — fetched at runtime so the header is always correct and
  // only the root package.json needs bumping. Falls back to the bundled
  // package.json version when running outside Electron (pure vite dev).
  const [appVersion, setAppVersion] = useState(APP_VERSION)
  useEffect(() => {
    if (window.electron?.getAppVersion) {
      window.electron.getAppVersion().then(setAppVersion).catch(() => {})
    }
  }, [])

  // Deep components (e.g. the Patreon CTA) can jump to Settings
  // without prop drilling through the detail views.
  const [settingsSection, setSettingsSection] = useState('general')
  useEffect(() => {
    const openSettings = event => {
      const section = event.detail?.section
      if (section === 'patreon') setSettingsSection('setup')
      else if (section) setSettingsSection(section)
      setAssistantOpen(false)
      setActiveTab('settings')
      setNucleomeTab('settings')
    }
    window.addEventListener('nucleus:open-settings', openSettings)
    return () => window.removeEventListener('nucleus:open-settings', openSettings)
  }, [])

  // Passive "a new release dropped" signal from Electron's background check:
  // a gold dot on the Settings tab (both modes) plus a one-time banner. The
  // banner dismissal is per-version, so the next release shows it again.
  const { update: availableUpdate } = useUpdateStatus()
  const [updateBannerDismissed, setUpdateBannerDismissed] = useState(
    () => localStorage.getItem('update_banner_dismissed') || ''
  )
  const dismissUpdateBanner = () => {
    if (availableUpdate) {
      localStorage.setItem('update_banner_dismissed', availableUpdate.version)
      setUpdateBannerDismissed(availableUpdate.version)
    }
  }
  const showUpdateBanner = Boolean(availableUpdate)
    && updateBannerDismissed !== availableUpdate?.version
    && !RECORD_MODE && !skinCreatorFullscreen

  // Download queue for nucleus:// imports
  const {
    currentDownload,
    phase,
    error,
    result,
    queueLength,
    queueDownload,
    clearDownload,
    proceedToNext,
    recoverFromError,
    retryWithSlippiAction,
    retryWithDuplicateAction
  } = useDownloadQueue()

  // Check if first-run setup is needed
  useEffect(() => {
    const checkSetupStatus = async () => {
      try {
        const data = await api.get('/setup/status');
        setSetupNeeded(!data.complete);
      } catch (err) {
        console.error('Failed to check setup status:', err);
        // On error, assume setup is not needed to avoid blocking the app
        setSetupNeeded(false);
      }
    };
    checkSetupStatus();
  }, []);

  const checkSetupHealth = async () => {
    try {
      const data = await api.post('/setup/health', {
        isoPath: localStorage.getItem('vanilla_iso_path') || ''
      });

      const problems = data.problems || [];
      setSetupProblems(problems);
      setSetupNoticeHidden(
        problems.length === 0
          || localStorage.getItem(SETUP_NOTICE_HIDDEN_KEY) === setupProblemSignature(problems)
      );
    } catch (err) {
      // Health check is advisory only — never block the app on it.
      console.error('Setup health check failed:', err);
    }
  };

  useEffect(() => {
    if (setupNeeded === false) {
      checkSetupHealth();
    }
  }, [setupNeeded]);

  useEffect(() => {
    // The catalog read is independent of baseline setup: it returns an empty
    // vault on a fresh profile instead of failing. Gating it on setupNeeded
    // left `loading` true forever once the fullscreen setup branch went away,
    // so an unconfigured profile sat on "Loading your vault..." and could not
    // browse or reach Randall at all (ASTRA-REVIEW-BB finding 11).
    if (setupNeeded !== null) {
      fetchMetadata();
    }

    // Listen for nucleus:// protocol imports. Any web page can open one, so
    // the window names the site and asks first (importLinkPrompt.js).
    if (window.electron?.onNucleusImport) {
      const cleanup = window.electron.onNucleusImport(async (data) => {
        console.log('[Nucleus] Import link received');
        if (!(await confirmImportLink(data, appConfirm))) return;
        const { url, name, title, type, effectType } = data;

        // Queue the download - the hook handles everything
        queueDownload({ url, name, title, type, effectType });
      });

      // Cleanup listener on unmount
      return cleanup;
    }
  }, [setupNeeded, queueDownload]);

  // Patreon OAuth handoff — the website's callback page deep-links back with
  // the app token; storing it flips every entitlement consumer via its event.
  // Any web page can open that link, so it is taken only within 15 minutes of a
  // link started here (and with its state, once the website echoes it), and
  // replacing a linked account with another asks first (patreonLinkGuard.js).
  useEffect(() => {
    if (!window.electron?.onNucleusPatreon) return undefined;
    return window.electron.onNucleusPatreon(async (payload) => {
      const taken = await decidePatreonLink(payload, {
        currentToken: getPatreonToken(),
        lookupName: async (token) => {
          const { invokeEdgeFunction } = await import('./shared/account/account');
          return (await invokeEdgeFunction('ai-entitlement', { token }))?.patreon_name || '';
        },
        confirm: ({ oldName, newName }) => appConfirm(
          `Replace the linked Patreon account${oldName ? ` (${oldName})` : ''} with `
          + `${newName ? `"${newName}"` : 'a different account'}? Your cloud sync and Randall usage would `
          + 'move to that account. Only say yes if you just linked it yourself.',
          { title: 'Switch Patreon account?', confirmText: 'Switch', cancelText: 'Keep current' }),
        refuse: () => appAlert(IGNORED_LINK_MESSAGE, { title: 'Patreon link ignored' }),
      });
      if (!taken) return;
      setPatreonToken(payload.token);
      playSound('start');
    });
  }, []);

  // The backend's automatic cloud upload needs that token too, and only this
  // window can read it: send it at launch and after every link/sign-out, not
  // just when Settings → Cloud happens to be open (see vaultTokenMirror).
  useEffect(() => {
    if (!NUCLEOME_ENABLED) return undefined;
    const mirror = createVaultTokenMirror({
      getToken: getPatreonToken,
      checkEntitlement: getEntitlement,
      post: (body) => api.post('/api/nucleome/vault/token', body),
      signOutPending: () => signOutPending(),
      clearSignOutPending: () => clearSignOutPending(),
    });
    mirror();
    window.addEventListener(ENTITLEMENT_EVENT, mirror);
    return () => window.removeEventListener(ENTITLEMENT_EVENT, mirror);
  }, []);

  // The user's own AI (MCP) spends the same Randall usage as the chat: the backend holds this window's Patreon
  // token in memory and checks the entitlement before each AI call (randall/assistant/mcpAccount.js).
  useEffect(() => {
    if (!ASSISTANT_ENABLED) return undefined;
    const mirror = createMcpAccountMirror({
      getToken: getPatreonToken,
      post: (body) => api.post('/api/mcp/account', body),
    });
    mirror();
    window.addEventListener(ENTITLEMENT_EVENT, mirror);
    return () => window.removeEventListener(ENTITLEMENT_EVENT, mirror);
  }, []);

  // test_in_game over MCP uses the Slippi Dolphin folder set in Settings: the backend holds it in memory
  // (randall/mcp/window.py); Settings and first-run setup fire SLIPPI_PATH_EVENT when it changes.
  useEffect(() => {
    if (!ASSISTANT_ENABLED) return undefined;
    const mirror = createMcpWindowMirror({
      getDolphinPath: () => localStorage.getItem('slippi_dolphin_path'),
      post: (body) => api.post('/api/mcp/window', body),
    });
    mirror();
    window.addEventListener(SLIPPI_PATH_EVENT, mirror);
    return () => window.removeEventListener(SLIPPI_PATH_EVENT, mirror);
  }, []);

  // Questions the user's own AI (MCP) must have answered here, in the window, not only in the AI client: connecting
  // a creation toolkit folder runs its Python (randall/mcp/window.py). Only this window can answer them.
  useEffect(() => {
    if (!ASSISTANT_ENABLED) return undefined;
    return createMcpConfirmWatcher({
      list: () => api.get('/api/mcp/window/confirmations'),
      ask: (item) => appConfirm(item.message, {
        title: item.title || 'Your AI asks', confirmText: item.confirm_text || 'Allow', cancelText: 'Deny',
      }),
      answer: (id, allowed) => api.post(`/api/mcp/window/confirmations/${encodeURIComponent(id)}`, { allowed }),
      subscribe: (refresh) => subscribeSocket({ mcp_confirm: refresh, connect: refresh }),
    });
  }, []);

  // All protocol listeners above are installed before this effect runs. The
  // main process retains cold-launch links through backend startup, first-run
  // setup, and slow renderer loads until this explicit handshake.
  useEffect(() => {
    window.electron?.protocolRendererReady?.().catch(() => {});
  }, []);

  // Handle download completion - refresh metadata and play sound
  useEffect(() => {
    if (phase === DOWNLOAD_PHASES.COMPLETE && result?.success) {
      playSound(result.cameraSound ? 'camera' : 'newSkin')
      fetchMetadata()
      setActiveTab('storage')
    }
  }, [phase, result]);

  // Handle setup completion
  const handleSetupComplete = () => {
    setShowFirstRunSetup(false);
    setSetupNeeded(false);
    setSettingsRefreshVersion(current => current + 1);
    fetchMetadata();
    checkSetupHealth();
  };

  const handleOpenFirstRunSetup = () => {
    setShowFirstRunSetup(true);
  };

  const handleCancelFirstRunSetup = () => {
    setShowFirstRunSetup(false);
  };

  const handleDismissSetupNotice = () => {
    setSetupNoticeHidden(true);
  };

  const handleNeverShowSetupNotice = () => {
    try {
      localStorage.setItem(SETUP_NOTICE_HIDDEN_KEY, setupProblemSignature(setupProblems));
    } catch (err) {
      console.error('Failed to persist setup notice dismissal:', err);
    }
    setSetupNoticeHidden(true);
  };

  // Handle slippi choice from download modal
  const handleDownloadSlippiChoice = async (choice) => {
    try {
      await retryWithSlippiAction(choice)
      // Success - effect will handle refresh and sound
    } catch (err) {
      // Error state is already set by the hook
      console.error('[Nucleus] Slippi retry failed:', err)
    }
  };

  // Handle duplicate choice from download modal
  const handleDownloadDuplicateChoice = async (choice) => {
    try {
      await retryWithDuplicateAction(choice)
      // Success - effect will handle refresh and sound
    } catch (err) {
      // Error state is already set by the hook
      console.error('[Nucleus] Duplicate retry failed:', err)
    }
  };

  // Handle download modal close
  const handleDownloadClose = () => {
    clearDownload()
  };

  // Show loading state while checking setup status
  if (setupNeeded === null) {
    return (
      <>
        <AppDialogHost />
        <BackendStoppedScreen />
        <div className="app">
          <div className="app-loading">
            <HexagonLoader size={88} decorative />
            <p>Checking setup status...</p>
          </div>
        </div>
      </>
    );
  }

  // ASTRA-ONBOARDING (2026-09-22): this used to replace the WHOLE app with
  // FirstRunSetup whenever the baseline assets were missing, which locked an
  // unconfigured person out of Randall and out of browsing -- the two things
  // that should work before anything is configured. Now the app renders, the
  // operations that genuinely need baseline assets gate themselves, and the
  // full setup screen is one click away on the banner below (the setup card
  // that used to sit in the assistant panel was removed with its home screen).
  return (
    <div className="app">
      <AppDialogHost />
      <BackendStoppedScreen />
      <InterruptedJobsNotice />
      {!(mode === 'nucleus' && skinCreatorFullscreen) && (
        <header className="app-header" ref={headerRef}>
          <BrandWordmark mode={mode} appVersion={RECORD_MODE ? null : appVersion} onToggle={NUCLEOME_ENABLED ? toggleMode : undefined} />
          {ASSISTANT_ENABLED && <McpImportChip />}
          {import.meta.env.DEV && !RECORD_MODE && <DebugTierToggle />}
          {mode === 'nucleome' ? (
            <NucleomeTabs
              activeTab={nucleomeTab}
              onTabChange={handleNucleomeTab}
              badgeTabId={availableUpdate ? 'settings' : null}
            />
          ) : (
          <nav className="app-tabs" onClick={(event) => {
            if (event.target.closest('button') && !event.target.closest('[data-assistant-toggle]')) setAssistantOpen(false)
          }}>
            <div className="upload-tab-anchor">
              <button
                className={`tab ${activeTab === 'upload' && !(assistantOpen) ? 'active' : ''} ${uploadAccount ? '' : 'tab--locked'}`}
                aria-disabled={!uploadAccount}
                onMouseEnter={playHoverSound}
                onClick={() => {
                  if (!uploadAccount) { playSound('back'); setShowUploadLock(current => !current); return }
                  if (activeTab !== 'upload') { playSound('boop'); setActiveTab('upload'); }
                }}
              >
                Upload
                {!uploadAccount && (
                  <svg className="tab-lock" viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="5" y="11" width="14" height="9" rx="2" />
                    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
                  </svg>
                )}
              </button>
              {showUploadLock && (
                <div className="upload-lock-popover" role="dialog" aria-label="Sign in required">
                  <button
                    type="button"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); setShowUploadLock(false); setActiveTab('settings'); }}
                  >
                    Sign in
                  </button>
                </div>
              )}
            </div>
            {ASSISTANT_ENABLED && <button data-assistant-toggle
              className={`tab ${assistantOpen ? 'active' : ''}`}
              aria-pressed={assistantOpen} onMouseEnter={() => { playHoverSound(); loadAssistantPanel() }}
              onClick={() => { if (!assistantOpen) playSound('boop'); setAssistantMounted(true); setAssistantOpen(true) }}>
              AI
            </button>}
            <button
              className={`tab ${activeTab === 'storage' && !(assistantOpen) ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (activeTab !== 'storage') { playSound('boop'); setActiveTab('storage'); } }}
            >
              Vault
            </button>
            <button
              className={`tab ${activeTab === 'mex' && !(assistantOpen) ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (activeTab !== 'mex') { playSound('boop'); setActiveTab('mex'); } }}
            >
              Install
            </button>
            <button
              className={`tab ${activeTab === 'settings' && !(assistantOpen) ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (activeTab !== 'settings') { playSound('boop'); setActiveTab('settings'); } }}
            >
              Settings
              {availableUpdate && <span className="tab-dot" aria-label="Update available" />}
            </button>
          </nav>
          )}
        </header>
      )}

      {showUpdateBanner && (
        <div className="update-banner" role="status">
          <div className="update-banner-text">
            <strong>v{availableUpdate.version} is available</strong>
            {availableUpdate.notes && <span className="update-banner-notes">{availableUpdate.notes}</span>}
          </div>
          <div className="update-banner-actions">
            <button
              className="setup-health-btn setup-health-btn--run"
              onMouseEnter={playHoverSound}
              onClick={() => {
                playSound('boop')
                dismissUpdateBanner()
                setSettingsSection('general')
                if (mode === 'nucleome') handleNucleomeTab('settings')
                else setActiveTab('settings')
              }}
            >
              Open Settings
            </button>
            <button
              className="setup-health-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); dismissUpdateBanner(); }}
              title="Hide this until the next release"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* One setup banner. A profile that never finished setup gets the plain
          "run setup" prompt (always shown); otherwise the boot health check's
          problems (dismissible). The two never show together. */}
      {mode === 'nucleus' && !skinCreatorFullscreen && setupNeeded && !showFirstRunSetup && (
        <div className="setup-health-banner" role="alert">
          <div className="setup-health-text">
            <strong>Not set up yet</strong>
            <ul><li>Run First-Time Setup to finish getting started. You can browse in the meantime.</li></ul>
          </div>
          <div className="setup-health-actions">
            <button
              className="setup-health-btn setup-health-btn--run"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); handleOpenFirstRunSetup(); }}
            >
              Run Setup
            </button>
          </div>
        </div>
      )}

      {mode === 'nucleus' && !skinCreatorFullscreen && !setupNeeded && setupProblems.length > 0 && !setupNoticeHidden && (
        <div className="setup-health-banner" role="alert">
          <div className="setup-health-text">
            <strong>First-time setup needs attention</strong>
            <ul>
              {setupProblems.map((problem) => (
                <li key={problem.id}>{problem.message}</li>
              ))}
            </ul>
          </div>
          <div className="setup-health-actions">
            <button
              className="setup-health-btn setup-health-btn--run"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); handleOpenFirstRunSetup(); }}
            >
              Run Setup
            </button>
            <button
              className="setup-health-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); handleDismissSetupNotice(); }}
            >
              Dismiss
            </button>
            <button
              className="setup-health-btn setup-health-btn--quiet"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); handleNeverShowSetupNotice(); }}
              title="Hide this notice until a different setup problem appears"
            >
              Don't show again
            </button>
          </div>
        </div>
      )}

      {/* nucleus content stays mounted (hidden) while in nucleOME mode so
          toggling back restores the vault/install state exactly as left. */}
      <EditorContext.Provider value={{ editor: assistantEditor, openEditor: openAssistantEditor, openStageVault: openAssistantStage,
        beginStageEditor: item => {
          setAssistantEditor({ kind: 'stage', stageCode: item.stageCode, skinId: item.id, character: item.character, name: item.name })
          setTextureRequest(null); setEditorSidebar(true); setAssistantMounted(true); setAssistantOpen(true)
        },
        closeEditor: closeAssistantEditor, closeHandler: editorCloseHandler, setEditorTexture, textureRequest, setTextureRequest,
        checkpoint: assistantCheckpoint, publishCheckpoint,
        hideSidebar: () => setEditorSidebar(false), showSidebar: () => setEditorSidebar(true) }}>
      <main className={`app-content ${nucleusEntering ? 'mode-enter' : ''} ${assistantOpen && !assistantEditor ? 'app-content--assistant-full' : ''} ${assistantEditor && editorSidebar ? 'app-content--assistant-editor' : ''}`}
            style={mode === 'nucleome' ? { display: 'none' } : undefined}>
        {loading ? (
          <div className="app-panel-loading">
            <HexagonLoader size={72} decorative />
            <p>Loading your vault...</p>
          </div>
        ) : (
          <>
            {shouldMountNucleusTab('upload') && (
              <div className={`app-panel app-panel--scroll ${activeTab === 'upload' ? '' : 'app-panel--hidden'}`}>
                <Suspense fallback={<PanelLoading>Loading upload...</PanelLoading>}>
                  <UploadPage metadata={metadata} account={uploadAccount} />
                </Suspense>
              </div>
            )}
            {shouldMountNucleusTab('storage') && (
              <div className={`app-panel app-panel--scroll ${activeTab === 'storage' ? '' : 'app-panel--hidden'}`}>
                <Suspense fallback={<PanelLoading>Loading your vault...</PanelLoading>}>
                  {/* the vault's edit modal is portaled out of this panel: it hides itself while the vault is not on
                      screen (vault/vaultActive.js) */}
                  <VaultActiveContext.Provider value={activeTab === 'storage' && !(assistantOpen && !assistantEditor)}>
                    <StorageViewer metadata={metadata} onRefresh={fetchMetadata} onSkinCreatorChange={setSkinCreatorFullscreen}
                      vaultNavigation={vaultNavigation} onVaultNavigationComplete={() => setVaultNavigation(null)}
                      onAssistantContext={ASSISTANT_ENABLED ? setVaultContext : undefined} />
                  </VaultActiveContext.Provider>
                </Suspense>
              </div>
            )}
            {shouldMountNucleusTab('mex') && (
              <div className={`app-panel app-panel--fill ${activeTab === 'mex' ? '' : 'app-panel--hidden'}`}>
                <Suspense fallback={<PanelLoading>Loading installer...</PanelLoading>}>
                  {/* the vault's Pose Manager (apply a pose to all) is portaled out of this panel too */}
                  <VaultActiveContext.Provider value={activeTab === 'mex' && !(assistantOpen && !assistantEditor)}>
                    <MexPanel active={activeTab === 'mex'} vaultMetadata={metadata} />
                  </VaultActiveContext.Provider>
                </Suspense>
              </div>
            )}
            {shouldMountNucleusTab('settings') && (
              <div className={`app-panel app-panel--scroll ${activeTab === 'settings' ? '' : 'app-panel--hidden'}`}>
                <Suspense fallback={<PanelLoading>Loading settings...</PanelLoading>}>
                  <Settings
                    key={settingsRefreshVersion}
                    section={settingsSection}
                    onSectionChange={setSettingsSection}
                    metadata={metadata}
                    onOpenFirstRunSetup={handleOpenFirstRunSetup}
                  />
                </Suspense>
              </div>
            )}
          </>
        )}
        {ASSISTANT_ENABLED && assistantMounted && <div className={`assistant-host ${assistantEditor ? editorSidebar ? 'assistant-host--editor' : 'assistant-host--hidden' : assistantOpen ? '' : 'assistant-host--hidden'}`}>
          <Suspense fallback={<PanelLoading>Loading assistant...</PanelLoading>}>
            <AssistantPanel visible={(assistantEditor ? editorSidebar : assistantOpen) && mode === 'nucleus'} account={account} vaultMetadata={metadata}
              onOpenProject={() => navigateFromAssistant(() => { setActiveTab('mex'); setAssistantOpen(false) })}
              context={{ page: activeTab, ...(activeTab === 'storage' ? vaultContext : {}) }}
              onRefresh={fetchMetadata} onOpenVault={(character, skinId) => navigateFromAssistant(() => {
                setVaultNavigation({ character, skinId })
                setActiveTab('storage'); setAssistantOpen(false)
              })}
              setupNeeded={setupNeeded === true}
              onSetupComplete={handleSetupComplete}
              onOpenFullSetup={handleOpenFirstRunSetup} />
          </Suspense>
        </div>}
      </main>
      </EditorContext.Provider>

      {/* nucleOME stays mounted (hidden) after first open, mirroring the
          nucleus <main> above — otherwise toggling modes mid-coach-turn
          unmounts CoachPage and kills the in-flight answer stream.
          display:contents keeps the wrapper out of layout when visible. */}
      {nucleomeMounted && (
        <div style={{ display: mode === 'nucleome' ? 'contents' : 'none' }}>
          <Suspense fallback={
            <main className="app-content">
              <PanelLoading>Loading Nucleus Stats...</PanelLoading>
            </main>
          }>
            <NucleomeApp
              activeTab={nucleomeTab}
              onTabChange={handleNucleomeTab}
              settingsContent={
                // Settings is SHARED between modes: same component, same props
                // as the nucleus instance, so both modes edit the same config.
                <Settings
                  key={`nucleome-${settingsRefreshVersion}`}
                  section={settingsSection}
                  onSectionChange={setSettingsSection}
                  metadata={metadata}
                  onOpenFirstRunSetup={handleOpenFirstRunSetup}
                  mode="nucleome"
                />
              }
            />
          </Suspense>
        </div>
      )}

      {/* Download modal for nucleus:// protocol imports */}
      <DownloadModal
        download={currentDownload}
        phase={phase}
        error={error}
        result={result}
        queueLength={queueLength}
        onClose={handleDownloadClose}
        onProceedToNext={proceedToNext}
        onRecoverFromError={recoverFromError}
        onSlippiChoice={handleDownloadSlippiChoice}
        onDuplicateChoice={handleDownloadDuplicateChoice}
      />

      {showFirstRunSetup && (
        <Suspense fallback={null}>
          <FirstRunSetup
            onComplete={handleSetupComplete}
            onCancel={handleCancelFirstRunSetup}
          />
        </Suspense>
      )}
    </div>
  )
}

export default App
