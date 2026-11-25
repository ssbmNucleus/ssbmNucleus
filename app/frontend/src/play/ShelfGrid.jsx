import ShelfCard from './ShelfCard'

/**
 * The shelf: one card per game, the built-in ones first, then games being added. `client` is
 * usePlayClient's install, update and cancel for the built-in cards (optional).
 */
export default function ShelfGrid({ entries, env, launcher, client = null, adding = null, renderActions, coverVersions = {} }) {
  return (
    <div className="play-grid">
      {entries.map((entry) => (
        <ShelfCard
          key={entry.id}
          entry={entry}
          env={env}
          active={launcher.active}
          last={launcher.lastByEntry[entry.id] || null}
          requestError={launcher.errors[entry.id] || null}
          onPlay={launcher.launch}
          onInstall={client?.install}
          onUpdate={client?.update}
          onCancelInstall={client?.cancel}
          coverVersion={coverVersions[entry.id]}
        >
          {renderActions ? (cardProps) => renderActions(entry, cardProps) : undefined}
        </ShelfCard>
      ))}
      {adding}
    </div>
  )
}
