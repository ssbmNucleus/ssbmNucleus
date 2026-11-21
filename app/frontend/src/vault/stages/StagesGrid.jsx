/**
 * StagesGrid - Stage grid display (Vault > Stages home)
 *
 * Features:
 * - 2 x 4 grid: the six DAS stages, Custom Stages, More Stages
 * - Stage icon display with fallback
 * - Variant / skin count display
 * - Skeleton loading state
 * - Click to select stage
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { BACKEND_URL } from '../../shared/config/config'

const DAS_STAGES = [
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: `${BACKEND_URL}/vanilla/stages/pokemon stadium.png` },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: `${BACKEND_URL}/vanilla/stages/yoshis story.png` },
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: `${BACKEND_URL}/vanilla/stages/dreamland.png` },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: `${BACKEND_URL}/vanilla/stages/fountain of dreams.png` },
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: `${BACKEND_URL}/vanilla/stages/battlefield.png` },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: `${BACKEND_URL}/vanilla/stages/final destination.png` }
]

const DAS_CODES = new Set(DAS_STAGES.map(s => s.code))

export default function StagesGrid({
  stageVariants,
  isLoading,
  onSelectStage,
  customStageCount = 0,
  onOpenCustomStages,
  onOpenMoreStages,
}) {
  // Skins for every stage that is not one of the six DAS stages. They live in
  // the same vault listing (storage/das/<folder>/), keyed by stage code.
  const moreStageSkinCount = Object.entries(stageVariants || {})
    .filter(([code]) => !DAS_CODES.has(code))
    .reduce((n, [, variants]) => n + variants.filter(v => v.type !== 'folder').length, 0)

  return (
    <div className="grid-wrapper">
      <div className="stages-grid stages-grid--eight">
        {isLoading ? (
          // Skeleton loading for stages (8 = the full 2 x 4 home grid)
          Array.from({ length: 8 }).map((_, idx) => (
            <div key={`skeleton-stage-${idx}`} className="stage-skeleton">
              <div className="skeleton-icon"></div>
              <div className="skeleton-text" style={{ width: '70%' }}></div>
              <div className="skeleton-text" style={{ width: '40%' }}></div>
            </div>
          ))
        ) : DAS_STAGES.map((stage) => {
          const variants = stageVariants[stage.code] || []
          const variantCount = variants.length
          const vanillaImagePath = stage.vanillaImage

          return (
            <div
              key={stage.code}
              className="stage-card"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onSelectStage(stage); }}
            >
              <div className="stage-icon-container">
                <img
                  src={vanillaImagePath}
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
                  <span>{variantCount}</span> variant{variantCount !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
          )
        })}

        {!isLoading && (
          <>
            <div
              className="stage-card custom-stages-gateway"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onOpenCustomStages && onOpenCustomStages(); }}
            >
              <div className="stage-icon-container">
                <div className="stage-placeholder" style={{ display: 'flex' }}>
                  +
                </div>
              </div>
              <div className="stage-info">
                <h3 className="stage-name">Custom Stages</h3>
                <p className="stage-variant-count">
                  <span>{customStageCount}</span> stage{customStageCount !== 1 ? 's' : ''}
                </p>
              </div>
            </div>

            <div
              className="stage-card custom-stages-gateway more-stages-gateway"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onOpenMoreStages && onOpenMoreStages(); }}
              title="Skins for every other versus stage (Peach's Castle, Corneria, Big Blue, ...)"
            >
              <div className="stage-icon-container">
                <div className="stage-placeholder" style={{ display: 'flex' }}>
                  ⋯
                </div>
              </div>
              <div className="stage-info">
                <h3 className="stage-name">More Stages</h3>
                <p className="stage-variant-count">
                  <span>{moreStageSkinCount}</span> skin{moreStageSkinCount !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
