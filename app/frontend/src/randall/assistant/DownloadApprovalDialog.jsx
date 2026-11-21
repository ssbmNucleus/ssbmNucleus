import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../shared/transport/api'

const typeName = type => ({ character_dat: 'Costume', stage_dat: 'Stage skin', xdelta: 'Patch' }[type] || type?.replaceAll('_', ' '))

// --- what the file is, in words a person who has never modded Melee would use -
// Two different promises are named here, and they are never merged into one
// sentence: DECLARED is what the publisher filed the post as, DETECTED is what
// the downloaded bytes turned out to be. Nothing here may fall back to a raw
// backend type -- a dialog that says `sss_background` is asking the user to
// learn our internals before they are allowed to consent to anything.
export const DECLARED_LABELS = {
  character_dat: 'a costume',
  stage_dat: 'a stage skin',
  effects_dat: 'character effects',
  other: 'not stated on the post',
}

export const DETECTED_LABELS = {
  character: 'a costume',
  character_renamed: 'a costume',
  custom_fighter_costume: 'a skin for a custom character',
  ic_half: 'one half of an Ice Climbers costume',
  stage: 'a stage skin',
  custom_stage: 'a custom stage',
  mex_stage_yml: 'a custom stage',
  custom_character: 'a whole custom character',
  mex_fighter_yml: 'a whole custom character',
  effect: 'a character effect',
  effect_image: 'a character effect',
  effect_unsupported: 'a character effect Nucleus cannot read',
  menu_mod: 'a menu picture',
  css_icon_grid: 'character-select icons',
  css_background: 'a character-select background',
  css_doors: 'character-select doors',
  sss_background: 'a stage-select background',
  pause_screen: 'a pause screen',
  percent_font: 'a damage-percent font',
  ready_go: 'the READY / GO / GAME graphics',
  bundle: 'a bundle of several mods',
  xdelta: 'an ISO patch (it rewrites a whole game build)',
  patch: 'an ISO patch (it rewrites a whole game build)',
  music: 'music',
  dolphin_textures: 'a Dolphin texture pack, which Nucleus does not import',
  sound_bank: 'a sound bank, which Nucleus does not import',
}

const humanize = type => String(type || '').replaceAll('_', ' ').trim()
export const declaredLabel = type => DECLARED_LABELS[type] || DETECTED_LABELS[type] || humanize(type) || 'not stated on the post'
export const detectedLabel = type => DETECTED_LABELS[type] || humanize(type) || 'something Nucleus could not name'

const sections = destination => String(destination || '').split(/[>\u203a]/).map(part => part.trim())
  .filter(Boolean).filter((part, index) => !(index === 0 && part.toLowerCase() === 'vault'))

/** The vault section a file lands in, said as a place rather than a breadcrumb. */
export function destinationPhrase(destination) {
  const text = String(destination || '').trim()
  if (!text) return 'a section Nucleus works out from the file itself'
  if (/^Not imported/i.test(text)) {
    const what = text.replace(/^Not imported\s*/i, '').replace(/[()]/g, '').trim()
    return `nowhere: Nucleus does not import ${what || 'this kind of file'}`
  }
  if (/^Decided from/i.test(text)) return 'a section Nucleus works out from the file itself'
  const parts = sections(text)
  if (!parts.length) return 'your vault'
  if (parts[0] === 'Menus') return `your vault\u2019s Menus section, under ${parts.slice(1).join(' \u203a ') || 'Menus'}`
  return `your vault\u2019s ${parts.join(' \u203a ')} section`
}

/** The approve button names the action and the place. Never "Approve". */
export function approveLabel(destination) {
  const text = String(destination || '').trim()
  if (!text || /^Not imported/i.test(text) || /^Decided from/i.test(text)) return 'Add to my vault'
  const section = (sections(text)[0] || '').replace(/\s*\(.*\)$/, '').trim()
  return section ? `Add to my ${section}` : 'Add to my vault'
}

/** The identity of the exact bytes, kept out of the way until someone wants it. */
export function FileIdentity({ detected, summary = 'Exactly which file this is', children }) {
  if (!detected || (!detected.type && !detected.sha256)) return null
  return <details className="assistant-download-identity"><summary>{summary}</summary>
    {children}
    <dl>
      {detected.type && <div><dt>Identified as</dt><dd>{detectedLabel(detected.type)}
        <small> ({detected.type}{detected.confidence ? `, ${detected.confidence} match` : ''})</small></dd></div>}
      {detected.destination && <div><dt>Goes into</dt><dd>{detected.destination}</dd></div>}
      {detected.sha256 && <div><dt>Fingerprint</dt>
        <dd><code title={detected.sha256}>{String(detected.sha256).slice(0, 12)}…</code></dd></div>}
    </dl>
  </details>
}

/** What this is, where it lands, and the one warning that changes the answer. */
export function DownloadFacts({ approval }) {
  const detected = approval.detected || null
  const mod = approval.website_mods?.[0] || {}
  const declared = approval.declared_types || []
  const destination = detected?.destination || (approval.destinations || [])[0] || ''
  const executables = detected?.executable_members || []
  const untrusted = Boolean(approval.content_is_untrusted || mod.content_is_untrusted)
  return <section className="assistant-download-facts" aria-label="What this is and where it goes">
    <p className="assistant-download-what"><strong>{detected
      ? `This is ${detectedLabel(detected.type)}.`
      : `The post says this is ${declared.map(declaredLabel).join(' and ') || 'not stated on the post'}.`}</strong>
      {' '}{detected ? `It goes into ${destinationPhrase(destination)}.`
        : destination ? `If that is what it is, it goes into ${destinationPhrase(destination)}.` : ''}</p>
    {!detected && <p className="assistant-download-check">Nucleus works out what the files really are before anything
      is written. If they are not what the post says, nothing is imported.</p>}
    {executables.length > 0 && <p className="assistant-download-warning" role="alert">
      This download carries {executables.length === 1 ? 'a program file' : 'program files'}
      {' '}({executables.slice(0, 3).join(', ')}). Nucleus never installs programs, so nothing here will be imported.</p>}
    {untrusted && <p className="assistant-download-warning">The words on this mod’s page were written by whoever
      posted it. Randall reads them as text, never as instructions, and nothing in them changes where this file lands.</p>}
    <FileIdentity detected={detected} />
  </section>
}

/** A bounded question, with the destination of each answer under it. */
export function DownloadChoice({ choice, choices, value, onChange, disabled }) {
  const options = choice?.options?.length
    ? choice.options.map(option => ({ ...option, id: option.id || option.key }))
    : (choices || [])
  if (!options.length) return null
  return <fieldset className="assistant-download-choices" disabled={disabled}>
    <legend>{choice?.question || 'Variants to add'}</legend>
    {options.map(option => <label key={option.id}>
      <input type="radio" name="review-variant" checked={value === option.id} onChange={() => onChange(option.id)} />
      <span>{option.label}
        {option.description && <small>{option.description}</small>}
        {option.destination && <small>Goes into {destinationPhrase(option.destination)}</small>}</span>
    </label>)}
  </fieldset>
}

function PreviewImage({ src, fallback, stock = false }) {
  const [failed, setFailed] = useState([])
  const image = [src, fallback].find(url => url && !failed.includes(url))
  return image ? <img className={stock ? 'review-mod-stock' : 'review-mod-csp'} src={image} alt={stock ? 'Stock icon' : 'Mod preview'} loading="lazy" onError={() => setFailed(values => [...values, image])} />
    : stock ? null : <span className="review-mod-csp review-mod-missing">No preview</span>
}

function Pages({ data, offset, onOffset, loading, label }) {
  if (!data || data.total <= 20) return null
  return <nav className="download-review-pages" aria-label={label}>
    <button disabled={loading || offset === 0} onClick={() => onOffset(Math.max(0, offset - 20))}>Previous</button>
    <span>{offset + 1}–{Math.min(offset + 20, data.total)} of {data.total.toLocaleString()}</span>
    <button disabled={loading || data.next_offset === null} onClick={() => onOffset(data.next_offset)}>Next</button>
  </nav>
}

export default function DownloadApprovalDialog({ approval, chatId, onDecision }) {
  const bulk = Boolean(approval.bulk_download)
  const dialog = useRef(null)
  const [choice, setChoice] = useState(approval.default_choice || approval.choice?.default || 'all')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [fileOffset, setFileOffset] = useState(0)
  const [data, setData] = useState(null)
  const [files, setFiles] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const element = dialog.current
    element.showModal()
    element.querySelector('h2')?.focus({ preventScroll: true })
    return () => element.close()
  }, [])
  useEffect(() => {
    let alive = true
    setLoading(true); setError('')
    const timer = setTimeout(() => {
      const endpoint = `/api/assistant/chats/${chatId}/approvals/${approval.id}/files`
      Promise.all([
        api.get(endpoint, { query: { choice: bulk ? 'all' : choice, kind: 'mods', query, offset } }),
        api.get(endpoint, { query: { choice: bulk ? 'all' : choice, kind: 'files', query, offset: fileOffset } }),
      ]).then(([mods, inventory]) => { if (alive) { setData(mods); setFiles(inventory) } })
        .catch(err => { if (alive) { setData(null); setFiles(null); setError(err.message) } })
        .finally(() => { if (alive) setLoading(false) })
    }, query ? 180 : 0)
    return () => { alive = false; clearTimeout(timer) }
  }, [chatId, approval.id, choice, query, offset, fileOffset, retry])
  const decide = async decision => {
    if (sending) return
    setSending(true); setError('')
    const asked = approval.choices?.length || approval.choice?.options?.length
    try { await onDecision(approval.id, decision, decision === 'approve' && asked ? choice : undefined) }
    catch (err) { setError(err.message) }
    finally { setSending(false) }
  }
  const summary = data?.summary || approval.contents_summary
  const mod = approval.website_mods[0]
  const changeQuery = value => { setQuery(value); setOffset(0); setFileOffset(0) }
  return createPortal(<dialog ref={dialog} className="assistant-download-dialog assistant-mod-review" aria-labelledby="download-review-title"
    onCancel={event => { event.preventDefault(); decide('deny') }}>
    <header><div><h2 id="download-review-title" tabIndex={-1}>{bulk ? `Download ${approval.website_mods.length} mods?` : `Download ${mod?.title}?`}</h2>
      {!bulk && (mod?.credit || mod?.author) && <p className="review-author">by {mod.credit || mod.author}</p>}
      <p>{bulk ? `${summary?.file_count ?? '…'} listed files · Add to vault` : <>You’re about to add {summary?.mod_count > 0 ? `${summary.mod_count.toLocaleString()} mod${summary.mod_count === 1 ? '' : 's'}` : 'this mod'} to your vault.</>}</p></div>
      <button className="download-review-close" aria-label="Cancel download" disabled={sending} onClick={() => decide('deny')}>×</button></header>
    {!bulk && <DownloadFacts approval={approval} />}
    {bulk && <label className="assistant-bulk-fix"><input type="checkbox" checked={choice === 'fix'} disabled={sending} onChange={event => setChoice(event.target.checked ? 'fix' : 'import_as_is')} />Fix unsafe skins</label>}
    {!bulk && <DownloadChoice choice={approval.choice} choices={approval.choices} value={choice} disabled={sending}
      onChange={id => { setChoice(id); setOffset(0); setFileOffset(0); setQuery('') }} />}
    {(summary?.mod_count > 20 || summary?.file_count > 20) && <div className="download-review-filters">
      <input type="search" aria-label="Search download contents" placeholder="Find a mod or file" value={query} onChange={event => changeQuery(event.target.value)} />
    </div>}
    <div className="review-content" aria-busy={loading}>
      {loading ? <p role="status">Loading previews…</p> : <>
        {bulk ? <ul className="review-mod-grid review-bulk-grid">{approval.website_mods.map(mod => <li className="review-mod-card" key={mod.post_id}>
          <PreviewImage src={mod.image} /><div><strong>{mod.title}</strong><span>{mod.credit || mod.author}</span>
            <span>{mod.selected_file?.name || `${mod.download_file_count} files`}</span></div>
        </li>)}</ul> : data?.items.length > 0 ? <ul className="review-mod-grid">{data.items.map((item, index) => <li className={`review-mod-card ${item.type !== 'character_dat' || item.image_is_post ? 'review-mod-landscape' : ''}`} key={`${choice}:${offset}:${index}`}>
          <div className="review-mod-art"><PreviewImage key={item.image || mod.image} src={item.image} fallback={mod.image} />{item.type === 'character_dat' && <PreviewImage key={item.stock_image} src={item.stock_image} stock />}</div>
          <div><strong>{[item.character, item.color].filter(Boolean).join(' · ') || typeName(item.type)}</strong>
            <span title={item.name}>{item.name}</span></div>
        </li>)}</ul> : query ? <p>No matching mods.</p> : <div className="review-mod-card review-mod-landscape">
          <div className="review-mod-art"><PreviewImage src={mod.image} /></div><div><strong>{mod.title}</strong></div>
        </div>}
        {!bulk && <Pages data={data} offset={offset} onOffset={setOffset} loading={loading} label="Included mod pages" />}
        <section className="review-files" aria-label="Files included">
          <h3>Files <span>{files?.total?.toLocaleString() ?? summary?.file_count}</span></h3>
          {files?.items.length > 0 ? <ul>{files.items.map((item, index) => <li key={`${fileOffset}:${index}`} title={item.name}>{item.name}</li>)}</ul>
            : <p>{query ? 'No matching files.' : 'The publisher has not listed the archive contents.'}</p>}
          <Pages data={files} offset={fileOffset} onOffset={setFileOffset} loading={loading} label="Download file pages" />
        </section>
      </>}
    </div>
    {error && <p className="assistant-error" role="alert">{error} {!data && <button onClick={() => setRetry(value => value + 1)}>Retry</button>}</p>}
    <footer><button disabled={sending} onClick={() => decide('deny')}>Cancel</button>
      <button className="download-review-confirm" disabled={sending || loading || !data || !files} onClick={() => decide('approve')}>{sending ? 'Adding…' : bulk ? `Add ${approval.website_mods.length} mods to my vault` : approveLabel(approval.detected?.destination || (approval.destinations || [])[0])}</button></footer>
  </dialog>, document.body)
}
