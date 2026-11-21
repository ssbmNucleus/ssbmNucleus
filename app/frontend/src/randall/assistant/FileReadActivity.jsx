import { INTERMEDIATE_TOOLS } from './activity'

// Match Ozone's collapsed work summary instead of giving every help lookup a
// card -- and do the same for the model-import steps that produce working
// material rather than something to look at. A twenty-step import used to fill
// the conversation with alignment, mesh and binding cards; it is now one
// evolving activity line, with the drafts and the comparison still in place.
// A step that failed or is waiting for the user is never folded away.
export function groupFileReads(tools = []) {
  const kind = tool => tool?.name === 'search_docs' ? 'docs'
    : ['search_vault', 'inspect_mod'].includes(tool?.name) ? 'vault'
      : (INTERMEDIATE_TOOLS.has(tool?.name) && !tool?.approval && !tool?.result?.error
        && !['error', 'denied', 'expired', 'cancelled', 'interrupted'].includes(tool?.status)) ? 'working' : null
  const groups = []
  for (const tool of tools) {
    const previous = groups.at(-1)
    if (kind(tool) && kind(tool) === kind(previous?.[0])) previous.push(tool)
    else groups.push([tool])
  }
  return groups
}

function VaultReadRows({ items = [] }) {
  const families = new Map()
  for (const item of items) {
    const key = JSON.stringify([item.character, item.name])
    if (!families.has(key)) families.set(key, { ...item, variants: new Set(), count: 0 })
    const family = families.get(key)
    family.count++
    if (item.variant) family.variants.add(item.variant)
  }
  return <ul className="assistant-read-list">{[...families].map(([key, item]) => <li key={key}>
    <div className="assistant-read-name"><strong>{item.name}</strong>{item.count > 1 && <span className="assistant-read-count">{item.count} variants</span>}</div>
    <span className="assistant-read-meta">{[item.character, [...item.variants].join(', ')].filter(Boolean).join(' · ')}</span>
  </li>)}</ul>
}

export function VaultReadActivity({ tools }) {
  const running = tools.some(tool => tool.status === 'running')
  const errors = tools.filter(tool => tool.result?.error || tool.status === 'error')
  const stopped = tools.some(tool => ['cancelled', 'interrupted', 'expired'].includes(tool.status))
  const label = running ? 'Checking vault' : errors.length === tools.length ? 'Could not check vault'
    : stopped ? 'Vault check stopped' : 'Checked vault'
  return <div className="assistant-file-activity">
    <details className="assistant-file-group">
      <summary>{label}<span className="assistant-file-chevron" aria-hidden="true">›</span></summary>
      <div className="assistant-file-body" tabIndex={0} role="region" aria-label="Vault lookup details">{tools.map(tool => <div className="assistant-read-section" key={tool.id}>
        <div className="assistant-read-heading"><span>{tool.name === 'inspect_mod' ? 'Skin details' : 'Vault search'}</span>
          <span>{tool.status === 'running' ? 'Searching…' : tool.result?.total != null ? `${tool.result.total} matches` : ''}</span></div>
        {tool.result?.items?.length > 0 && <VaultReadRows items={tool.result.items} />}
      </div>)}</div>
    </details>
    {errors.map(tool => <p className="assistant-error" role="alert" key={tool.id}>{tool.result?.error || 'Could not check the vault.'}</p>)}
  </div>
}

export default function FileReadActivity({ tools, renderExcerpt }) {
  const files = new Map()
  for (const tool of tools) for (const source of tool.result?.sources || []) {
    const title = source.title || 'Nucleus help'
    if (!files.has(title)) files.set(title, new Set())
    if (source.excerpt) files.get(title).add(source.excerpt)
  }
  const running = tools.some(tool => tool.status === 'running')
  const errors = tools.filter(tool => tool.result?.error || tool.status === 'error')
  const stopped = tools.some(tool => ['cancelled', 'interrupted', 'expired'].includes(tool.status))
  const label = running ? 'Reading Nucleus help'
    : files.size ? `Read ${files.size} help page${files.size === 1 ? '' : 's'}`
      : errors.length ? 'Could not read the help'
        : stopped ? 'Stopped reading the help'
          : 'Nothing in the built-in help covered that — ask Randall and he can answer from what he knows'
  return <div className="assistant-file-activity">
    {files.size > 0 ? <details className="assistant-file-group">
      <summary>{label}<span className="assistant-file-chevron" aria-hidden="true">›</span></summary>
      <div className="assistant-file-body" tabIndex={0} role="region" aria-label="File lookup details">{[...files].map(([title, excerpts]) => <details key={title}>
        <summary>{title}</summary>
        <div className="coach-md">{[...excerpts].map((excerpt, index) => <div key={index}>{renderExcerpt(excerpt)}</div>)}</div>
      </details>)}</div>
    </details> : <div className="assistant-file-label" role="status">{label}</div>}
    {errors.map(tool => <p className="assistant-error" role="alert" key={tool.id}>{tool.result?.error || 'Could not read Nucleus help.'}</p>)}
  </div>
}
