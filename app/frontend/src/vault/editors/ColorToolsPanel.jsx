import ColorPalettePanel from './ColorPalettePanel'
import MaterialColorsPanel from './MaterialColorsPanel'
import LayersPanel from './LayersPanel'
import ReferencePanel from './ReferencePanel'
import { texturesInPaintScope } from './paintProtocol'

// The color tools beside the texture strip: palette, materials (single
// models only), layers and the reference image, one tab at a time.
export default function ColorToolsPanel({
  panelSizes, skinCreatorLoading, isSaving, connectionFailed, paletteTab,
  setPaletteTab, palette, paintMembers, materialColors, layers,
  canvasOwner, selectedTextureId, layerAction, beginLayerEdit, drawColor,
  setDrawColor, modelTextures, paletteScope, setPaletteScope,
}) {
  return (
    <div className="editor-color-tools" style={{ width: panelSizes.colorToolsWidth }} inert={skinCreatorLoading || isSaving || connectionFailed}>
    <div className="editor-color-toolbar">
    {/* Materials are per-model, so the pair editor hides that tab --
        Reference is just an image you copy colors from, so it is
        offered to everyone, climbers included. */}
    <div className="editor-color-tabs" role="tablist" aria-label="Color tools">
      <button type="button" role="tab" aria-selected={paletteTab === 'textures'} onClick={() => setPaletteTab('textures')}>Color palette</button>
      {!paintMembers.length && <button type="button" role="tab" aria-selected={paletteTab === 'materials'} onClick={() => { setPaletteTab('materials'); materialColors.load() }}>Materials</button>}
      <button type="button" role="tab" aria-selected={paletteTab === 'layers'} onClick={() => setPaletteTab('layers')}>Layers</button>
      <button type="button" role="tab" aria-selected={paletteTab === 'reference'} onClick={() => setPaletteTab('reference')}>Reference</button>
    </div>
    </div>
    {paletteTab === 'layers' ? <LayersPanel
      layers={layers.layers}
      activeId={layers.activeId}
      disabled={canvasOwner !== selectedTextureId}
      onSelect={layers.setActiveLayer}
      onAdd={layerAction(layers.addLayer)}
      onDuplicate={layerAction(layers.duplicateLayer)}
      onDelete={layerAction(layers.deleteLayer)}
      onMove={layerAction(layers.moveLayer)}
      onMergeDown={layerAction(layers.mergeDown)}
      onSetProp={layerAction(layers.setLayerProp)}
      onBeginEdit={beginLayerEdit}
      onLiveProp={(id, patch) => layers.setLayerProp(id, patch, { live: true })}
      onEndEdit={layers.commit}
    />
      : paletteTab === 'reference' ? <ReferencePanel drawColor={drawColor} setDrawColor={setDrawColor} />
      : paletteTab === 'materials' && !paintMembers.length ? <MaterialColorsPanel controls={materialColors} /> : <ColorPalettePanel
      height="100%"
      palette={palette}
      textureCount={texturesInPaintScope(modelTextures, paletteScope).length}
      paintMembers={paintMembers}
      scope={paletteScope}
      onScopeChange={async scope => { try { await palette.flushColorAdjustments(); palette.clearPaletteState(); setPaletteScope(scope) } catch {} }}
    />}
    </div>
  )
}
