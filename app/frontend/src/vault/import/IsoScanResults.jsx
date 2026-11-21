import { useEffect, useState } from 'react'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { playHoverSound, playSound } from '../../shared/audio/sounds'
import { describeScanResults, scanItemName, scanFileName } from './isoScanResultModel'
import './IsoScanResults.css'

export function ScanIcon({ kind = 'disc', ...props }) {
  const paths = {
    disc: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2.5" /><path d="M5.7 9a7 7 0 0 1 3.3-3.3M15 18.3a7 7 0 0 0 3.3-3.3" /></>,
    skins: <><path d="m8 4-5 3 3 5 2-1v9h8v-9l2 1 3-5-5-3a4 4 0 0 1-8 0Z" /></>,
    characters: <><circle cx="10" cy="8" r="3" /><path d="M4 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 2 4v2" /></>,
    stages: <><path d="M3 18h18M5 18v-5h5v5m4 0V7h5v11M3 7l4-3 4 3" /></>,
    das: <><path d="m12 3 10 5-10 5L2 8Zm-9 9 9 5 9-5M3 16l9 5 9-5" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <path d="m9 5 7 7-7 7" />,
    warning: <><path d="m12 3 10 18H2Z" /><path d="M12 9v4m0 4v.1" /></>,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[kind] || paths.disc}</svg>
}

function ResultImage({ src, name, kind }) {
  const [failed, setFailed] = useState(false)
  return <div className={`iso-result-image ${kind}`}>
    {src && !failed
      ? <img src={backendMediaUrl(src)} alt="" loading="lazy" draggable={false} onError={() => setFailed(true)} />
      : <div className="iso-result-fallback" role="img" aria-label={`${name}: preview unavailable`}><ScanIcon kind={kind} /></div>}
  </div>
}

const SKIP_REASONS = [
  ['dupes', 'Duplicates'],
  ['slippi_matched', 'Slippi matches'], ['data_mod', 'Gameplay-only changes'],
  ['custom_fighter', 'Custom character files'], ['preview_failed', 'Preview unavailable'],
]

function VaultCards({ items, kind, catalog = [], skipped = false, failedKeys }) {
  return <div className={`iso-added-cards ${kind} ${skipped ? 'iso-vault-cards' : ''}`}>
    {items.map((item, index) => {
      const name = scanItemName(item)
      const metadata = catalog.find(entry => kind === 'das'
        ? entry.id === item.id && entry.stageCode === item.stageCode
        : entry.name?.toLowerCase() === name.toLowerCase())
      const src = item.csp_url || item.icon_url || item.screenshotUrl || metadata?.screenshotUrl || metadata?.icon_url
      const failed = failedKeys?.has(item.key)
      return <article className={`iso-added-card${failed ? ' iso-card-failed' : ''}`} key={`${name}-${index}`}>
        <ResultImage src={src} name={name} kind={kind} />
        {failed && <span className="iso-card-issue" role="img" aria-label="Import failed" title="Import failed"><ScanIcon kind="warning" /></span>}
        <div className="iso-added-caption">
          <div className="iso-added-title"><strong title={name}>{name}</strong>
            {(item.character || item.stageName) && <span>{item.character || item.stageName}</span>}
          </div>
        </div>
      </article>
    })}
  </div>
}

export default function IsoScanResults({ characters, customSummary, stats, extractionFailures,
  skippedVault = [], scanSkins, scanError, importResult, selected, onToggleSkin, onToggleCharacter,
  onSelectAll, onSelectNone, onImport, onClose, refreshError, refreshing = false, onRetryRefresh }) {
  const result = describeScanResults({ characters, customSummary, scanSkins, importResult, extractionFailures, scanError, stats })
  const [active, setActive] = useState(result.initialCategory)
  const [collapsed, setCollapsed] = useState(new Set())
  const [catalogs, setCatalogs] = useState({})
  const category = result.categories.find(c => c.key === active)
  const summary = customSummary?.[active]
  const vaultItems = active === 'skins' ? skippedVault : summary?.skipped || []
  const vaultCount = active === 'skins' ? (vaultItems.length || stats?.existing || 0) : vaultItems.length
  const skipped = SKIP_REASONS.filter(([key]) => stats?.[key] > 0)
  const skippedCount = skipped.reduce((n, [key]) => n + stats[key], 0)
  const action = callback => () => { playSound('boop'); callback() }
  const completed = !result.ready && result.added > 0 && !result.issues && !refreshError
  const skinNames = new Map(Object.entries(characters).flatMap(([char, skins]) =>
    skins.map(skin => [skin.key, `${char} ${skin.costume_code}`])))
  const importErrors = importResult?.errors || []

  // Scan responses contain names; resolve actual vault icons after the import.
  // Preview lookup is optional and never delays or changes the scan result.
  useEffect(() => {
    const controller = new AbortController()
    for (const [key, route, field] of [
      ['characters', '/custom-characters/list', 'characters'],
      ['stages', '/custom-stages/list', 'stages'],
      ['das', '/das/storage/variants', 'variants'],
    ]) {
      if (!customSummary?.[key]?.imported.length && !customSummary?.[key]?.skipped.length) continue
      api.get(route, { signal: controller.signal }).then(data => {
        const entries = Array.isArray(data?.[field]) ? data[field] : []
        if (!controller.signal.aborted) setCatalogs(prev => ({ ...prev, [key]: entries }))
      }).catch(() => {})
    }
    return () => controller.abort()
  }, [customSummary])

  return <div className="iso-scan-report" data-scan-complete="true">
    <div className="iso-result-categories" role="group" aria-label="Result categories">
      {result.categories.map(c => <button key={c.key} type="button"
        className={`iso-result-category ${active === c.key ? 'active' : ''}`}
        aria-pressed={active === c.key} disabled={!c.scanned}
        aria-label={`${c.label}: ${!c.scanned ? 'not scanned' : c.ready ? `${c.ready} to import` : c.added ? `${c.added} added` : 'nothing new'}${c.issues ? `, ${c.issues} issues` : ''}`}
        onClick={action(() => setActive(c.key))} onMouseEnter={playHoverSound}>
        <span className="iso-category-label">{c.label}</span>
        {(c.ready > 0 || c.added > 0) && <span className="iso-category-value">{c.ready || c.added}</span>}
        {c.issues > 0 && <span className="iso-category-issue" title={`${c.issues} issues`}><ScanIcon kind="warning" /></span>}
      </button>)}
    </div>

    <div className="iso-report-body">
    {refreshError && <div className="iso-scan-warning" role="alert">{refreshError}</div>}
    {scanError && <div className="iso-scan-warning" role="alert"><strong>Character skin scan failed</strong><p>{scanError}</p></div>}
    {extractionFailures.length > 0 && <div className="iso-scan-warning" role="alert">
      <strong>Could not read {extractionFailures.length} ISO{extractionFailures.length === 1 ? '' : 's'}</strong>
      <p>{extractionFailures.map(scanFileName).join(', ')}</p>
    </div>}

    <section className="iso-result-panel" aria-label={category.label}>
      {active === 'skins' && importErrors.length > 0 && <div className="iso-result-errors iso-import-errors" role="alert">
        <strong>{importResult.unconfirmed ? 'Import interrupted' : 'Could not import'}</strong>
        <ul>{importErrors.map((error, index) => <li key={index}>{typeof error === 'string' ? error : `${skinNames.get(error.key) || error.key}: ${error.error}`}</li>)}</ul>
      </div>}
      {active === 'skins' && !importResult && category.ready > 0 && <>
        <div className="iso-review-toolbar">
          <span><strong>{selected.size}</strong> of {category.ready} selected</span>
          <button type="button" onClick={action(onSelectAll)}>Select all</button>
          <button type="button" onClick={action(onSelectNone)}>Clear</button>
        </div>
        <div className="iso-skin-groups">
          {Object.entries(characters).sort(([a], [b]) => a.localeCompare(b)).map(([char, skins]) => {
            const count = skins.filter(s => selected.has(s.key)).length
            const closed = collapsed.has(char)
            return <section key={char} className="iso-skin-group" style={{ '--skin-count': skins.length }}>
              <div className="iso-skin-group-heading">
                <button type="button" aria-expanded={!closed} onClick={action(() => setCollapsed(prev => {
                  const next = new Set(prev); if (next.has(char)) next.delete(char); else next.add(char); return next
                }))}><ScanIcon kind="arrow" className={closed ? '' : 'expanded'} /><strong>{char}</strong><span>{count} / {skins.length}</span></button>
                <button type="button" onClick={action(() => onToggleCharacter(char))}>{count === skins.length ? 'Clear group' : 'Select group'}</button>
              </div>
              {!closed && <div className="iso-skin-cards">{skins.map(skin => <button key={skin.key} type="button"
                className={`iso-skin-card ${selected.has(skin.key) ? 'selected' : ''}`}
                aria-pressed={selected.has(skin.key)} aria-label={`${char} ${skin.costume_code}`}
                onClick={action(() => onToggleSkin(skin.key))} onMouseEnter={playHoverSound}>
                <ResultImage src={skin.csp_url} name={char} kind="skins" />
                <span className="iso-skin-check">{selected.has(skin.key) && <ScanIcon kind="check" />}</span>
                <span className="iso-skin-caption"><strong>{skin.costume_code}</strong><span title={skin.source_iso}>{scanFileName(skin.source_iso)}</span></span>
              </button>)}</div>}
            </section>
          })}
        </div>
      </>}

      {active !== 'skins' && summary?.imported.length > 0 &&
        <VaultCards items={summary.imported} kind={active} catalog={catalogs[active]} />}

      {category.added === 0 && category.ready === 0 && vaultCount === 0 && !(active === 'skins' && importResult) && <div className="iso-result-empty">
        <ScanIcon kind={category.issues ? 'warning' : active} />
        <strong>{category.issues ? 'Some content could not be imported' : 'Nothing new'}</strong>
      </div>}
      {active === 'skins' && importResult && <>
        <p className="iso-import-outcome" role="status">{importResult.unconfirmed ? 'Import not confirmed'
          : importResult.imported > 0 ? `${importResult.imported} character skin${importResult.imported === 1 ? '' : 's'} saved to vault`
            : 'No character skins saved'}</p>
        <VaultCards kind="skins" failedKeys={new Set(importErrors.map(error => error.key))}
          items={Object.entries(characters).sort(([a], [b]) => a.localeCompare(b)).flatMap(([, skins]) => skins).filter(skin => selected.has(skin.key))
          .map(skin => ({ ...skin, name: skinNames.get(skin.key) }))} />
      </>}
      {active === 'skins' && stats?.preview_failed > 0 && <div className="iso-result-errors" role="alert">
        {stats.preview_failed} character skin preview{stats.preview_failed === 1 ? '' : 's'} could not be generated. These were skipped.
      </div>}
      {vaultCount > 0 && <section className="iso-vault-section" aria-label="Already in vault">
        <h4>Already in vault <span>{vaultCount}</span></h4>
        <VaultCards items={vaultItems} kind={active} catalog={catalogs[active]} skipped />
      </section>}
      {summary?.errors.length > 0 && <div className="iso-result-errors" role="alert">
        <strong>Could not import</strong>
        <ul>{summary.errors.map((error, index) => <li key={index}>{typeof error === 'string' ? error : `${error.key}: ${error.error}`}</li>)}</ul>
      </div>}
    </section>

    {skippedCount > 0 && <details className="iso-result-details iso-skip-details">
      <summary>{skippedCount} other character skin files skipped</summary>
      <div className="iso-skip-grid">{skipped.map(([key, label]) => <div key={key}><strong>{stats[key]}</strong><span>{label}</span></div>)}</div>
    </details>}
    </div>

    <footer className="iso-report-footer">
      <span>{result.ready ? `${selected.size} character skin${selected.size === 1 ? '' : 's'} selected` : ''}</span>
      <button type="button" className={result.ready || refreshError ? 'btn-cancel' : 'btn-save'} disabled={refreshing}
        onClick={() => { playSound(completed ? 'start' : 'back'); onClose() }} onMouseEnter={playHoverSound}>
        {result.ready ? 'Close without importing' : completed ? 'Done' : 'Close'}
      </button>
      {result.ready > 0 && <button type="button" className="btn-save" disabled={!selected.size} onClick={onImport} onMouseEnter={playHoverSound}>
        Import &amp; finish<ScanIcon kind="arrow" />
      </button>}
      {refreshError && <button type="button" className="btn-save" disabled={refreshing} onClick={onRetryRefresh} onMouseEnter={playHoverSound}>
        {refreshing ? 'Refreshing…' : 'Refresh vault'}
      </button>}
    </footer>
  </div>
}
