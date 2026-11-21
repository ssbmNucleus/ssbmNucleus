import { useState } from 'react'
import { backendMediaUrl } from '../../shared/config/config'
import { downloadReceiptItems } from './downloadReceipts'
import StageModCard from './StageModCard'
import { FileIdentity, declaredLabel, destinationPhrase, detectedLabel } from './DownloadApprovalDialog'

function ReceiptImage({ src, fallback, kind, name }) {
  const [failed, setFailed] = useState([])
  const image = [src, fallback].find(url => url && !failed.includes(url))
  const label = kind === 'csp' ? 'CSP' : kind === 'stock' ? 'stock icon' : 'preview'
  return image ? <img className={`assistant-receipt-${kind}`} src={backendMediaUrl(image)} alt={`${name} ${label}`} onError={() => setFailed(values => [...values, image])} />
    : <span className={`assistant-receipt-${kind} is-missing`}>No {label}</span>
}

// A download the importer refused: what arrived, why that is not what was
// approved, and the one thing left to do. The backend's own sentence names the
// internal types, so it is kept for the details panel and the headline says the
// same thing in the words the approval used.
export function RefusedDownload({ result }) {
  const detected = result.detected || {}
  const declared = (result.declared_types || []).map(declaredLabel).join(' and ')
  const executables = detected.executable_members || []
  return <section className="assistant-download-refused" role="alert" aria-label="Nothing was added to your vault">
    <p className="assistant-receipt-title">Nothing was added to your vault.</p>
    {executables.length > 0
      ? <p>This download carries {executables.length === 1 ? 'a program file' : 'program files'}
        {' '}({executables.slice(0, 3).join(', ')}). Nucleus never installs programs, so nothing was imported.</p>
      : detected.type
        ? <p>This file is {detectedLabel(detected.type)}, {declared ? `not ${declared} as the post said.` : 'not what the post said it was.'}
          {detected.destination ? ` A file like this belongs in ${destinationPhrase(detected.destination)}.` : ''}</p>
        : <p>{result.error}</p>}
    {result.note && <p className="assistant-receipt-note">{result.note}</p>}
    <p className="assistant-settled-next">Open the mod on the website and look at it yourself if this is really what you want.</p>
    <FileIdentity detected={detected} summary="What Nucleus found in the file">
      {result.error && <p className="assistant-receipt-note">{result.error}</p>}
    </FileIdentity>
  </section>
}

// The importer needs an answer before anything can land. Each answer says where
// it would put the file, because that is the whole difference between them.
export function ChoiceNeeded({ result }) {
  const choice = result.choice || {}
  return <section className="assistant-download-choice-needed" role="status" aria-label="This file can be used in more than one way">
    <p className="assistant-receipt-title">Nothing was added yet: this file can be used in more than one way.</p>
    {choice.question && <p>{choice.question}</p>}
    <ul className="assistant-choice-options">{(choice.options || []).map(option => <li key={option.key || option.id}>
      <strong>{option.label}</strong>
      {option.description && <span>{option.description}</span>}
      {option.destination && <small>Goes into {destinationPhrase(option.destination)}</small>}
    </li>)}</ul>
    {result.note && <p className="assistant-settled-next">{result.note}</p>}
  </section>
}

export default function DownloadReceipt({ result, onOpenVault }) {
  if (result.choice_required) return <ChoiceNeeded result={result} />
  if (result.error || result.approval_status === 'denied') return <RefusedDownload result={result} />
  const items = downloadReceiptItems(result)
  const detected = result.detected || null
  // A repeat of a download that already finished changed nothing: saying "Added"
  // over a vault that did not move is the one thing this receipt must not do.
  const repeat = Boolean(result.repeat_of_completed_download)
  return <section className="assistant-download-receipt" aria-label={repeat ? 'Already in your vault' : 'Added to vault'}>
    <p className="assistant-receipt-title" role="status">{repeat ? 'Already in your vault'
      : <>✓ Added to vault <span>{result.imported_count}</span></>}</p>
    {detected?.destination && <p className="assistant-receipt-where">{repeat ? 'It is in ' : 'Added to '}
      {destinationPhrase(detected.destination)}.</p>}
    <div className="assistant-receipt-items">{items.map(item => {
      if (item.kind === 'stage') return <StageModCard key={`stage:${item.folder}:${item.id}`} item={item} />
      const costume = item.kind === 'costume'
      const Tag = costume ? 'button' : 'div'
      return <Tag key={`${item.kind}:${item.folder || item.character || ''}:${item.id}`} className={`assistant-receipt-item ${costume ? '' : 'assistant-receipt-wide'}`}
        {...(costume ? { disabled: item.unavailable, onClick: () => onOpenVault(item.character, item.id), 'aria-label': `Open ${item.name} ${item.variant || ''} in vault` } : {})}>
        <ReceiptImage key={item.image} src={item.image} fallback={item.unavailable ? null : item.fallback_image} kind={costume ? 'csp' : 'preview'} name={item.name} />
        {costume && <ReceiptImage key={item.stock_image} src={item.stock_image} kind="stock" name={item.name} />}
        <span><strong>{item.name}</strong><small>{item.stage || item.character || item.label}{item.variant ? ` · ${item.variant}` : ''}{item.count > 1 ? ` · ${item.count} added` : ''}{item.unavailable ? ' · Removed from vault' : ''}</small></span>
      </Tag>
    })}</div>
    {repeat && result.note && <p className="assistant-receipt-note">{result.note}</p>}
    {result.skipped_count > 0 && <small>{result.skipped_count} already in your vault</small>}
    {result.fixed_count > 0 && <small>{result.fixed_count} Slippi {result.fixed_count === 1 ? 'fix applied' : 'fixes applied'}</small>}
    {result.unsafe_count > 0 && <p className="assistant-error" role="alert">{result.unsafe_count} costume{result.unsafe_count === 1 ? ' is' : 's are'} still not Slippi safe.</p>}
    <FileIdentity detected={detected} summary="Exactly which file was added" />
  </section>
}
