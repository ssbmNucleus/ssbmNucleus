import './ExportHome.css'

/**
 * Minimalist export home — three one-shot actions:
 *   Export ISO    : build a ready-to-play ISO.
 *   Export Patch  : build the ISO, then make a small .xdelta patch (one click).
 *   Add Bundle    : texture-pack ISO + auto HD portraits + patch -> .ssbm vault.
 *
 * Export ISO and Export Patch each carry their OWN Advanced tab (CSP compression
 * + Color Smash) scoped to that export. Bundles always ship full-res textures.
 *
 * The name box edits a base name only; ".iso" is shown as a fixed suffix and
 * appended at save time (and stripped if the user types it).
 */
const AdvancedPanel = ({ adv, recommendedCompression }) => (
  <div className="card-advanced">
    <button className="advanced-toggle" onClick={() => adv.setOpen(!adv.open)}>
      <span className="toggle-arrow">{adv.open ? '▼' : '▶'}</span>
      Advanced
    </button>

    {adv.open && (
      <div className="advanced-content">
        <div className="form-group">
          <label>
            CSP Compression
            {recommendedCompression < 1 && (
              <span className="hint-recommended"> · {recommendedCompression}x recommended</span>
            )}
          </label>
          <div className="compression-input-group">
            <input
              type="number"
              min="0.1"
              max="1.0"
              step="0.01"
              value={adv.compression}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (!isNaN(v) && v >= 0.1 && v <= 1.0) adv.setCompression(v);
              }}
              className="compression-number-input"
            />
            <span className="compression-multiplier">x</span>
          </div>
          <input
            type="range"
            min="0.1"
            max="1.0"
            step="0.01"
            value={adv.compression}
            onChange={(e) => adv.setCompression(parseFloat(e.target.value))}
            className="compression-slider"
          />
          <div className="compression-hints">
            <span className="hint-label">0.1 (Tiny)</span>
            <span className="hint-label">1.0 (Full)</span>
          </div>
        </div>

        <div className="form-group color-smash-group">
          <label className="color-smash-label">
            <input
              type="checkbox"
              checked={adv.colorSmash}
              onChange={(e) => adv.setColorSmash(e.target.checked)}
              className="color-smash-checkbox"
            />
            <span>Enable Color Smash</span>
          </label>
          <p className="color-smash-info">Saves memory but adds artifacts.</p>
        </div>
      </div>
    )}
  </div>
);

const CardWithAdvanced = ({ accent, title, desc, button, onClick, disabled, reason, adv, recommendedCompression }) => (
  <div className={`export-option accent-${accent} has-advanced ${disabled ? 'disabled' : ''}`}>
    <div className="export-option-main">
      <div className="option-text">
        <h3>{title}</h3>
        <p>{desc}</p>
        {disabled && reason && <p className="option-reason">{reason}</p>}
      </div>
      <button className="btn-option" onClick={onClick} disabled={disabled}>{button}</button>
    </div>
    <AdvancedPanel adv={adv} recommendedCompression={recommendedCompression} />
  </div>
);

const ExportOption = ({ accent, title, desc, button, onClick, disabled, reason }) => (
  <div className={`export-option accent-${accent} ${disabled ? 'disabled' : ''}`}>
    <div className="option-text">
      <h3>{title}</h3>
      <p>{desc}</p>
      {disabled && reason && <p className="option-reason">{reason}</p>}
    </div>
    <button className="btn-option" onClick={onClick} disabled={disabled}>
      {button}
    </button>
  </div>
);

const ExportHome = ({
  name,
  setName,
  recommendedCompression,
  slippiPath,
  vanillaPath,
  iso,
  patch,
  onExportIso,
  onExportPatch,
  onAddBundle,
}) => {
  const hasVanilla = !!vanillaPath;
  const hasSlippi = !!slippiPath;

  const bundleReason = !hasVanilla && !hasSlippi
    ? 'Set your vanilla ISO and Slippi paths in Settings'
    : !hasVanilla
    ? 'Set your vanilla ISO path in Settings'
    : !hasSlippi
    ? 'Set your Slippi / Dolphin path in Settings'
    : null;

  return (
    <div className="export-home">
      <div className="form-group filename-group">
        <label htmlFor="export-name">Output name</label>
        <div className="name-input-wrap">
          <input
            id="export-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value.replace(/\.iso$/i, ''))}
            spellCheck={false}
          />
          <span className="name-suffix">.iso</span>
        </div>
      </div>

      <div className="export-options">
        <CardWithAdvanced
          accent="cyan"
          title="Export ISO"
          desc="A ready-to-play ISO, auto-compressed to fit console / Wii."
          button="Export"
          onClick={onExportIso}
          adv={iso}
          recommendedCompression={recommendedCompression}
        />
        <ExportOption
          accent="gold"
          title="Save Bundle"
          desc="HD texture pack + patch, saved to your Patches library."
          button="Save"
          onClick={onAddBundle}
          disabled={!hasVanilla || !hasSlippi}
          reason={bundleReason}
        />
        <CardWithAdvanced
          accent="teal"
          title="Export Patch"
          desc="Create an .xdelta patch to share."
          button="Export"
          onClick={onExportPatch}
          disabled={!hasVanilla}
          reason={!hasVanilla ? 'Set your vanilla ISO path in Settings' : null}
          adv={patch}
          recommendedCompression={recommendedCompression}
        />
      </div>
    </div>
  );
};

export default ExportHome;
