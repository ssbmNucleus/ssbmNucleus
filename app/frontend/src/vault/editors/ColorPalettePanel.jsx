// Tool palette panel containing the batch Color Palette controls.
// `palette` is the object returned by useColorPalette.
export default function ColorPalettePanel({ height, palette, textureCount, paintMembers = [], scope, onScopeChange }) {
  const {
    colorPaletteEnabled,
    colorGroups,
    isAnalyzing,
    analysisError,
    maxColorGroups,
    setMaxColorGroups,
    selectedColorGroup,
    setSelectedColorGroup,
    analyzeColors,
    resetColorPalette,
    handleColorAdjust
  } = palette

  const scopeLabel = paintMembers.length ? (scope === "both" ? "Popo + Nana" : scope === "nana" ? "Nana only" : "Popo only") : palette.materialSupport ? ({both: 'Textures + materials', textures: 'Textures', materials: 'Materials'}[palette.paletteTarget]) : "All textures"

  return (
    <div className="skin-creator-tool-palette" style={{ height }}>

      <div className="tool-palette-content">
        {/* Batch Tools (Color Palette) */}
        <div className="tool-section">
          <div className="tool-section-content">
            {palette.materialSupport && !colorPaletteEnabled && <label className="skin-creator-palette-scope">
              Recolor
              <select aria-label="Palette colors" value={palette.paletteTarget} disabled={isAnalyzing || palette.isApplying} onChange={event => palette.setPaletteTarget(event.target.value)}>
                <option value="both">Textures + materials</option>
                <option value="textures">Textures only</option>
                <option value="materials">Materials only</option>
              </select>
            </label>}
            {paintMembers.length > 0 && !colorPaletteEnabled && (
              <label className="skin-creator-palette-scope">
                Adjust textures for
                <select value={scope} onChange={event => onScopeChange(event.target.value)}>
                  <option value="popo">Popo only</option>
                  <option value="nana">Nana only</option>
                  <option value="both">Both Popo and Nana</option>
                </select>
              </label>
            )}
            {/* Color Palette */}
            <div className="tool-palette-section-header">
              <span className="tool-palette-section-title">{colorPaletteEnabled ? scopeLabel : "Color groups"}</span>
              <div className="palette-controls">
                {!colorPaletteEnabled && (
                  <input
                    type="number"
                    className="max-groups-input"
                    min="2"
                    max="16"
                    value={maxColorGroups}
                    onChange={(e) => setMaxColorGroups(Math.min(16, Math.max(2, parseInt(e.target.value) || 8)))}
                    title="Max color groups"
                  />
                )}
                {!colorPaletteEnabled ? (
                  <button
                    className="palette-analyze-btn"
                    onClick={analyzeColors}
                    disabled={isAnalyzing || palette.isApplying || (textureCount === 0 && !palette.materialSupport)}
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze'}
                  </button>
                ) : (
                  <button
                    className="palette-reset-btn"
                    onClick={resetColorPalette}
                    title="Restore colors from before this analysis"
                    disabled={palette.isApplying}
                  >
                    Reset
                  </button>
                )}
              </div>
            </div>

            {analysisError && <div role="alert" className="palette-loading">{analysisError}</div>}
            {isAnalyzing && (
              <div className="palette-loading">
                Analyzing colors...
              </div>
            )}

            {colorPaletteEnabled && colorGroups.length > 0 && (
              <>
                {/* Color Grid */}
                <div className="color-grid" role="group" aria-label="Color groups">
                  {colorGroups.map((group, index) => {
                    const isSelected = selectedColorGroup === group.id
                    const hasChanges = group.hueShift !== 0 || group.saturationShift !== 0
                    const currentColor = `hsl(${(group.centerHue + group.hueShift + 360) % 360}, ${Math.max(0, Math.min(100, group.avgSaturation + group.saturationShift))}%, ${group.avgLightness}%)`
                    return (
                      <button
                        type="button"
                        aria-label={`Color group ${index + 1}`}
                        aria-pressed={isSelected}
                        key={group.id}
                        className={`color-grid-item ${isSelected ? 'selected' : ''} ${hasChanges ? 'modified' : ''}`}
                        onClick={() => setSelectedColorGroup(isSelected ? null : group.id)}
                        title="Select this color group"
                      >
                        <div className="color-grid-swatch" style={{ background: currentColor }} />
                        {hasChanges && <div className="color-grid-original" style={{ background: group.displayColor }} />}
                      </button>
                    )
                  })}
                </div>

                {/* Expanded Controls for Selected Color */}
                {selectedColorGroup && colorGroups.find(g => g.id === selectedColorGroup) && (() => {
                  const group = colorGroups.find(g => g.id === selectedColorGroup)
                  return (
                    <div className="color-editor">
                      <div className="color-editor-header">
                        <div className="color-editor-swatches">
                          <div className="color-swatch-original" style={{ background: group.displayColor }} />
                          <span className="color-arrow">{'->'}</span>
                          <div
                            className="color-swatch"
                            style={{
                              background: `hsl(${(group.centerHue + group.hueShift + 360) % 360}, ${Math.max(0, Math.min(100, group.avgSaturation + group.saturationShift))}%, ${group.avgLightness}%)`
                            }}
                          />
                        </div>
                        <button
                          className="color-reset-btn"
                          onClick={() => handleColorAdjust(group.id, 'reset', 0)}
                          disabled={group.hueShift === 0 && group.saturationShift === 0}
                        >
                          Reset
                        </button>
                      </div>
                      <div className="color-editor-sliders">
                        <div className="slider-row">
                          <label>Hue</label>
                          <div
                            className="slider-track"
                            style={{
                              background: `linear-gradient(to right,
                                hsl(${(group.centerHue - 180 + 360) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${(group.centerHue - 120 + 360) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${(group.centerHue - 60 + 360) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${group.centerHue}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${(group.centerHue + 60) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${(group.centerHue + 120) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%),
                                hsl(${(group.centerHue + 180) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%))`
                            }}
                          >
                            <input
                              type="range"
                              className="color-slider"
                              aria-label="Hue"
                              min="-180"
                              max="180"
                              value={group.hueShift}
                              onChange={(e) => handleColorAdjust(group.id, 'hueShift', parseInt(e.target.value))}
                            />
                            <div
                              className="slider-thumb-indicator"
                              style={{
                                left: `${((group.hueShift + 180) / 360) * 100}%`,
                                background: `hsl(${(group.centerHue + group.hueShift + 360) % 360}, ${group.avgSaturation}%, ${group.avgLightness}%)`
                              }}
                            />
                          </div>
                          <span className="slider-value">{group.hueShift > 0 ? '+' : ''}{group.hueShift}</span>
                        </div>
                        <div className="slider-row">
                          <label>Sat</label>
                          <div
                            className="slider-track sat-track"
                            style={{
                              background: `linear-gradient(to right,
                                hsl(${(group.centerHue + group.hueShift + 360) % 360}, 0%, ${group.avgLightness}%),
                                hsl(${(group.centerHue + group.hueShift + 360) % 360}, 100%, ${group.avgLightness}%))`
                            }}
                          >
                            <input
                              type="range"
                              className="color-slider"
                              aria-label="Saturation"
                              min="-100"
                              max="100"
                              value={group.saturationShift}
                              onChange={(e) => handleColorAdjust(group.id, 'saturationShift', parseInt(e.target.value))}
                            />
                            <div
                              className="slider-thumb-indicator"
                              style={{
                                left: `${((group.saturationShift + 100) / 200) * 100}%`,
                                background: `hsl(${(group.centerHue + group.hueShift + 360) % 360}, ${Math.max(0, Math.min(100, group.avgSaturation + group.saturationShift))}%, ${group.avgLightness}%)`
                              }}
                            />
                          </div>
                          <span className="slider-value">{group.saturationShift > 0 ? '+' : ''}{group.saturationShift}</span>
                        </div>
                      </div>
                    </div>
                  )
                })()}
              </>
            )}

            {colorPaletteEnabled && colorGroups.length === 0 && (
              <div className="no-colors-found">
                No color groups detected
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
