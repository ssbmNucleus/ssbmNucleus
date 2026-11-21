import { useState, useEffect, useRef } from 'react';
import { playSound } from '../../shared/audio/sounds';
import { API_URL, backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { useJob } from '../../shared/jobs/useJobs'
import { jobPercent } from '../../shared/jobs/jobOutcome'
import { downloadPatchFile } from '../../vault/patches/patchDownload'
import { getProgressMessage } from '../../shared/ui/progressText';
import ProgressPanel from '../../shared/ui/ProgressPanel';
import ExportHome from './ExportHome';
import LargeRosterWarning from '../LargeRosterWarning';
import { acceptStepStart, advance, stepMeta } from './exportPipeline';
import '../../shared/ui/ExportModal.css';
import './IsoBuilder.css';

// Minimalist export flow. Three one-shot pipelines run start-to-finish with no
// post-export menus (exportPipeline.js):
//   iso    : build ISO -> done
//   patch  : build ISO -> xdelta patch -> done
//   bundle : build texture-pack ISO -> auto-apply HD textures -> .ssbm in vault
// Each step is a backend job; the panel follows that job's record in the job
// store (core/jobs.py, shared/jobs) and starts the next step when it is done.
//
// phase: home | working | done | error
const STEP_TEXT = {
  export: { title: 'Building ISO…', message: 'Starting…' },
  patch: { title: 'Creating patch…', message: 'Comparing ISOs…' },
  textures: { title: 'Applying HD texture pack…', message: 'Computing portrait names…' },
  package: { title: 'Packaging bundle…', message: 'Building patch + bundle…' },
};

const IsoBuilder = ({ onClose, projectName = 'game', fighters, fightersStatus, onReloadRoster }) => {
  const getDefaultName = () => {
    const now = new Date();
    const date = now.toISOString().slice(0, 10);
    const time = now.toTimeString().slice(0, 5).replace(':', '-');
    return `${projectName}_${date}_${time}`;
  };

  const [phase, setPhase] = useState('home');
  const [error, setError] = useState(null);

  // The name box edits a base name (no extension); ".iso" is appended on save.
  const [baseName, setBaseName] = useState(getDefaultName());
  const filename = `${baseName.trim() || 'game'}.iso`;
  const [recommendedCompression, setRecommendedCompression] = useState(1.0);
  // Per-action Advanced settings (ISO and Patch each scope their own).
  const [isoCompression, setIsoCompression] = useState(1.0);
  const [isoColorSmash, setIsoColorSmash] = useState(false);
  const [isoAdvancedOpen, setIsoAdvancedOpen] = useState(false);
  const [patchCompression, setPatchCompression] = useState(1.0);
  const [patchColorSmash, setPatchColorSmash] = useState(false);
  const [patchAdvancedOpen, setPatchAdvancedOpen] = useState(false);

  // ISO save-to-disk state (Electron native-dialog path)
  const [saveState, setSaveState] = useState('idle'); // idle | saving | saved | error
  const [savedPath, setSavedPath] = useState(null);
  const [saveError, setSaveError] = useState(null);

  // settings paths (read once)
  const [slippiDolphinPath] = useState(() => localStorage.getItem('slippi_dolphin_path') || '');
  const [vanillaIsoPath] = useState(() => localStorage.getItem('vanilla_iso_path') || '');

  // The run: { action, step, jobId, filename, useTexturePack, exported,
  // textures, patch, bundle }. `filename` is the name this build was started
  // with: the name box's timestamp is frozen at modal open, and editing it
  // after a build must not point Save at a file that was never exported.
  // runRef is the run the handlers act on; `run` is what renders.
  const [run, setRun] = useState(null);
  const runRef = useRef(null);
  const job = useJob(run?.jobId || null);

  const setCurrentRun = (next) => {
    runRef.current = next;
    setRun(next);
  };

  const action = run?.action || null;
  const exported = run?.exported || null;
  const exportWarnings = Array.isArray(exported?.warnings) ? exported.warnings : [];
  const bundleName = () => (run?.filename || filename).replace(/\.iso$/i, '');

  const fail = (msg) => {
    if (runRef.current) setCurrentRun({ ...runRef.current, jobId: null });
    playSound('error');
    setError(msg);
    setPhase('error');
  };

  // Start one step's job; the run follows it once its id is known. A run
  // replaced meanwhile (a new export, or the panel closed) ignores the answer.
  const startStep = async (current, post, failText, idOf = (data) => data.job_id) => {
    try {
      const data = await post();
      const next = acceptStepStart(runRef.current, current, data, idOf);
      if (next) setCurrentRun(next);
    } catch (err) {
      if (runRef.current !== current) return;
      // err.data => the backend reported the failure itself
      fail(err.data ? (err.message || failText) : `${failText}: ${err.message}`);
    }
  };

  const beginStep = (next) => {
    setCurrentRun(next);
    if (next.step === 'patch') {
      startStep(next, () => api.post('/xdelta/create', {
        vanillaIsoPath,
        moddedIsoPath: next.exported.path,
        name: next.filename.replace(/\.iso$/i, ''),
        description: '',
      }), 'Failed to create patch');
    } else if (next.step === 'textures') {
      startStep(next, () => api.post('/texture-pack/auto-apply', {
        buildId: next.exported.buildId, slippiPath: slippiDolphinPath,
      }), 'Failed to apply texture pack');
    } else if (next.step === 'package') {
      const formData = new FormData();
      formData.append('name', next.filename.replace(/\.iso$/i, ''));
      formData.append('description', '');
      formData.append('buildName', next.exported.buildId || next.filename.replace(/\.iso$/i, ''));
      formData.append('vanillaIsoPath', vanillaIsoPath);
      formData.append('exportedIsoPath', next.exported.path);
      if (next.textures?.texturePackPath) formData.append('texturePackPath', next.textures.texturePackPath);
      startStep(next, () => api.post('/bundle/export', formData), 'Failed to create bundle');
    }
  };

  // The current step's job changed: wait, fail, start the next step, or finish.
  useEffect(() => {
    const decision = advance(runRef.current, job);
    if (!decision) return;
    if (decision.fail) {
      fail(decision.fail);
    } else if (decision.next) {
      beginStep(decision.next);
    } else {
      setCurrentRun(decision.done);
      playSound('achievement');
      setPhase('done');
    }
  }, [job]);

  // A closed panel stops following: its jobs finish on their own.
  useEffect(() => () => { runRef.current = null; }, []);

  // recommended compression on mount -> seed the slider value
  useEffect(() => {
    api.get('/recommended-compression')
      .then((data) => {
        setRecommendedCompression(data.ratio);
        setIsoCompression(data.ratio);
        setPatchCompression(data.ratio);
      })
      .catch((err) => console.error('Failed to fetch recommended compression:', err));
  }, []);

  // ---- kick off a pipeline ----
  const runExport = ({ act, useTexturePack, compression = 1.0, colorSmash = false }) => {
    playSound('start');
    setError(null);
    setSaveState('idle');
    setSavedPath(null);
    setSaveError(null);
    const next = { action: act, step: 'export', jobId: null, filename, useTexturePack };
    setCurrentRun(next);
    setPhase('working');
    startStep(next, () => api.post('/export/start', {
      filename,
      cspCompression: compression,
      useColorSmash: colorSmash,
      texturePackMode: useTexturePack,
      slippiDolphinPath: useTexturePack ? slippiDolphinPath : null,
    }), 'Failed to start export', (data) => data.artifactId);
  };

  const onExportIso = () => runExport({ act: 'iso', useTexturePack: false, compression: isoCompression, colorSmash: isoColorSmash });
  const onExportPatch = () => runExport({ act: 'patch', useTexturePack: false, compression: patchCompression, colorSmash: patchColorSmash });
  const onAddBundle = () => runExport({ act: 'bundle', useTexturePack: true });

  // working panel: the step's own text until its job reports
  const stepText = STEP_TEXT[run?.step] || STEP_TEXT.export;
  const progressTitle = run?.step === 'export' && run.useTexturePack
    ? 'Building texture-pack ISO…' : stepText.title;
  const progress = (run?.jobId && job?.id === run.jobId ? jobPercent(job) : null) ?? 0;
  const message = (run?.jobId && job?.id === run.jobId && job.detail) || stepText.message;

  const handleClose = () => {
    playSound('back');
    onClose();
  };

  const handleDownload = async () => {
    playSound('start');
    const builtFilename = run?.filename || filename;
    const artifactId = exported?.artifactId;
    // Electron: native save dialog + server-side copy (/export/save). The old
    // anchor download streamed 1.5 GB through Chromium; closing the app killed
    // the stream mid-copy and the truncated ISO booted to a black screen.
    if (window.electron?.saveIsoDialog) {
      const dest = await window.electron.saveIsoDialog(builtFilename);
      if (!dest) return;
      setSaveState('saving');
      setSaveError(null);
      try {
        const data = await api.post('/export/save', {
          artifactId, filename: builtFilename, destination: dest,
        });
        playSound('achievement');
        setSavedPath(data.path);
        setSaveState('saved');
      } catch (err) {
        playSound('error');
        // 409 = the backend refused for a stated reason (still building /
        // build failed) — its message is user-ready, show it verbatim.
        setSaveError(err.message || 'Failed to save ISO');
        setSaveState('error');
      }
      return;
    }
    // Browser fallback (dev server outside Electron): plain download.
    const link = document.createElement('a');
    link.href = backendMediaUrl(`${API_URL}/export/download/${artifactId}/${encodeURIComponent(builtFilename)}`);
    link.download = builtFilename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleDownloadPatch = async () => {
    setSaveState('saving');
    setSaveError(null);
    try {
      await downloadPatchFile(run?.patch?.patch_id);
      setSaveState('idle');
    } catch (err) {
      setSaveError(err.message || 'Failed to download patch');
      setSaveState('error');
    }
  };

  // Bundle downloads now happen from the vault (Patches → Bundles), not here.

  // ---- done screens ----
  // Warnings MexCLI attached to the build (the export job's result.warnings):
  // today that is the character-select memory guard, which compresses
  // portraits when the CSS files would overflow the game's heap and freeze the
  // select screen.
  const renderExportWarnings = () => (
    exportWarnings.length > 0 ? (
      <div className="warning-box export-warnings">
        {exportWarnings.map((w, i) => <p key={i}>{w}</p>)}
      </div>
    ) : null
  );

  const renderDone = () => {
    const patchResult = run?.patch;
    const bundleResult = run?.bundle;
    if (action === 'patch' && patchResult) {
      return (
        <div className="export-complete">
          <div className="success-icon">✓</div>
          <h3>Patch Created</h3>
          {renderExportWarnings()}
          <p className="subtle-line">
            {patchResult.size_mb} MB
            {patchResult.size_mb < 25 && <span className="discord-ok"> · Discord-friendly</span>}
            {' · saved to your Patches library'}
          </p>
          {saveError && <p className="subtle-line" role="alert">Patch download failed: {saveError}</p>}
          <div className="complete-actions">
            <button className="btn-download" onClick={handleDownloadPatch} disabled={saveState === 'saving'}>
              {saveState === 'saving' ? 'Preparing download…' : 'Download Patch'}
            </button>
            <button className="btn-secondary" onClick={handleClose}>Done</button>
          </div>
        </div>
      );
    }
    if (action === 'bundle' && bundleResult) {
      return (
        <div className="export-complete">
          <div className="success-icon">✓</div>
          <h3>Bundle Added</h3>
          <p className="subtle-line">
            “{bundleName()}” · {bundleResult.size_mb} MB
            {bundleResult.texture_count > 0 && ` · ${bundleResult.texture_count} HD portraits`}
          </p>
          <p className="share-note">
            Saved to your vault under <strong>Patches → Bundles</strong>, where you
            can rename it, add a cover, or download/share it.
          </p>
          <div className="complete-actions">
            <button className="btn-secondary btn-gold" onClick={handleClose}>Done</button>
          </div>
        </div>
      );
    }
    // iso
    return (
      <div className="export-complete">
        <div className="success-icon">✓</div>
        <h3>ISO Ready</h3>
        {renderExportWarnings()}
        {saveState === 'saved' ? (
          <p className="subtle-line">Saved to {savedPath}</p>
        ) : saveState === 'error' ? (
          <p className="subtle-line">Save failed: {saveError}</p>
        ) : saveState === 'saving' ? (
          <p className="subtle-line">Saving… keep the app open.</p>
        ) : (
          <p>Your modified ISO is ready to save.</p>
        )}
        <div className="complete-actions">
          <button
            className="btn-download"
            onClick={handleDownload}
            disabled={saveState === 'saving'}
          >
            {saveState === 'saving' ? 'Saving…'
              : saveState === 'saved' ? 'Save Another Copy'
              : `Save ${run?.filename || filename}`}
          </button>
          <button
            className="btn-secondary"
            onClick={handleClose}
            disabled={saveState === 'saving'}
          >
            Done
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="iso-builder-overlay">
      <div className="iso-builder-modal">
        <div className="modal-header">
          <h2>Export Project</h2>
          <button className="close-btn" onClick={handleClose}>×</button>
        </div>

        <div className="modal-body">
          {phase === 'home' && (
            <>
            <LargeRosterWarning fighters={fighters} status={fightersStatus} showUnknown onRetry={onReloadRoster} />
            <ExportHome
              name={baseName}
              setName={setBaseName}
              recommendedCompression={recommendedCompression}
              slippiPath={slippiDolphinPath}
              vanillaPath={vanillaIsoPath}
              iso={{
                compression: isoCompression, setCompression: setIsoCompression,
                colorSmash: isoColorSmash, setColorSmash: setIsoColorSmash,
                open: isoAdvancedOpen, setOpen: setIsoAdvancedOpen,
              }}
              patch={{
                compression: patchCompression, setCompression: setPatchCompression,
                colorSmash: patchColorSmash, setColorSmash: setPatchColorSmash,
                open: patchAdvancedOpen, setOpen: setPatchAdvancedOpen,
              }}
              onExportIso={onExportIso}
              onExportPatch={onExportPatch}
              onAddBundle={onAddBundle}
            />
            </>
          )}

          {phase === 'working' && (
            <ProgressPanel
              title={progressTitle}
              label="Export progress"
              progressValue={progress > 0 ? progress : null}
              metaText={run ? stepMeta(run.action, run.step) : null}
              messageText={getProgressMessage(message, 'Preparing…')}
            />
          )}

          {phase === 'done' && renderDone()}

          {phase === 'error' && (
            <div className="export-error">
              <div className="error-icon">✕</div>
              <h3>Export Failed</h3>
              <p className="error-message">{error}</p>
              <div className="complete-actions">
                {exported?.path && (
                  <button className="btn-download" onClick={handleDownload}>Download ISO Anyway</button>
                )}
                <button className="btn-secondary" onClick={handleClose}>Close</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default IsoBuilder;
