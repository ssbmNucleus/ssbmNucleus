/**
 * MoreStagesGrid - Vault sub-page listing every versus stage that is not one
 * of the six DAS stages (from the backend stage catalog), each with its
 * stage-select icon and how many skins the vault holds for it.
 *
 * Picking a stage hands a {code, name, folder} stage object back to the
 * StorageViewer, which renders the ordinary StageDetailView for it -- the
 * same variants page (sort, folders, drag reorder, rename, delete, export)
 * the six DAS stages use. Skins live in storage/das/<folder>/ for all 29.
 */
import { useEffect, useMemo, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'

const SkeletonCard = () => (
  <div className="stage-card skeleton-card">
    <div className="stage-icon-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '60%', height: '12px' }}></div>
  </div>
)

/** Non-folder variant count for one stage code in the grouped variants map. */
export function countStageSkins(stageVariants, code) {
  return (stageVariants?.[code] || []).filter(v => v.type !== 'folder').length
}

export default function MoreStagesGrid({ stageVariants, isLoading, onSelectStage, onBack }) {
  const [catalog, setCatalog] = useState([])
  const [catalogLoading, setCatalogLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/stages/catalog')
      .then(data => { if (!cancelled) setCatalog((data.stages || []).filter(s => !s.legal)) })
      .catch(err => console.error('Failed to fetch stage catalog:', err))
      .finally(() => { if (!cancelled) setCatalogLoading(false) })
    return () => { cancelled = true }
  }, [])

  const stages = useMemo(() => catalog.map(stage => ({
    code: stage.code,
    name: stage.name,
    folder: stage.folder,
    series: stage.series,
    vanillaImage: backendMediaUrl(stage.artUrl),
    count: countStageSkins(stageVariants, stage.code),
  })), [catalog, stageVariants])

  const loading = isLoading || catalogLoading

  return (
    <div className="grid-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap', width: '100%' }}>
        <button
          className="mode-btn"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('back'); onBack() }}
        >
          ← Back to Stages
        </button>
      </div>

      <div className="custom-stages-grid">
        {loading ? (
          Array.from({ length: 8 }).map((_, idx) => <SkeletonCard key={`skeleton-ms-${idx}`} />)
        ) : stages.map(stage => (
          <div
            key={stage.code}
            className={`stage-card ${stage.count === 0 ? 'more-stage-card--empty' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onSelectStage(stage) }}
            title={`${stage.name} (${stage.code})`}
          >
            <div className="stage-icon-container">
              <img
                src={stage.vanillaImage}
                alt={stage.name}
                className="stage-icon"
                draggable={false}
                onError={(e) => {
                  e.target.style.display = 'none'
                  e.target.nextSibling.style.display = 'flex'
                }}
              />
              <div className="stage-placeholder" style={{ display: 'none' }}>
                {stage.name[0]}
              </div>
            </div>
            <div className="stage-info">
              <h3 className="stage-name">{stage.name}</h3>
              <p className="stage-variant-count">
                <span>{stage.count}</span> variant{stage.count !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
