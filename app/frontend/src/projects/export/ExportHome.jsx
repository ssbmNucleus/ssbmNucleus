import { useRef, useState } from 'react'
import './ExportHome.css'
import MeleeUnlockedCard from './MeleeUnlockedCard'
import { COVER_TYPES, coverProblem } from '../../shared/jobs/shelfAdd'

/**
 * Minimalist export home — three one-shot actions:
 *   Export ISO    : build a ready-to-play ISO.
 *   Export Patch  : build the ISO, then make a small .xdelta patch (one click).
 *   Add Bundle    : texture-pack ISO + auto HD portraits + patch -> .ssbm vault.
 * and one that builds no ISO: Melee Unlocked (MeleeUnlockedCard.jsx), fighter
 * plugins for the project's custom fighters. With Play on (a `shelf` prop), a fifth:
 *   Add to Play   : build the ISO, then put it on Play's shelf (a shelf_add job).
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

// Add to Play: the ISO export, then the game onto Play's shelf with a name, a
// description (plain text; the shelf trims and caps them) and, if one is chosen, a cover
// picture (else the disc's banner is used). A picture is checked when it is chosen
// (shared/jobs/shelfAdd.js coverProblem), not after the build.
const ShelfOption = ({ shelf, onClick }) => {
  const coverRef = useRef(null);
  const [coverError, setCoverError] = useState(null);
  const chooseCover = (event) => {
    const file = event.target.files?.[0] || null;
    event.target.value = '';
    if (!file) return;
    const problem = coverProblem(file);
    setCoverError(problem);
    if (!problem) shelf.setCover(file);
  };
  return (
    <div className="export-option accent-violet has-advanced shelf-option">
      <div className="export-option-main">
        <div className="option-text">
          <h3>Add to Unlocked</h3>
          <p>Build the ISO and put it on your Unlocked shelf, ready to play in Melee Unlocked or Dolphin.</p>
        </div>
        <button className="btn-option" onClick={onClick}>Add</button>
      </div>
      <div className="card-advanced">
        <button className="advanced-toggle" onClick={() => shelf.setOpen(!shelf.open)}>
          <span className="toggle-arrow">{shelf.open ? '▼' : '▶'}</span>
          Name, description and cover
        </button>
        {shelf.open && (
          <div className="advanced-content">
            <div className="form-group">
              <label htmlFor="shelf-name">Name on the shelf</label>
              <input id="shelf-name" type="text" maxLength={80} value={shelf.name}
                onChange={(e) => shelf.setName(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="shelf-description">Description</label>
              <textarea id="shelf-description" rows={2} maxLength={1000} value={shelf.description}
                onChange={(e) => shelf.setDescription(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Cover picture</label>
              <input ref={coverRef} type="file" accept={COVER_TYPES} hidden onChange={chooseCover} />
              <p>
                {shelf.cover ? shelf.cover.name : "None chosen: the disc's banner is used."}{' '}
                <button className="btn-mu-source" onClick={() => coverRef.current?.click()}>Choose...</button>
                {shelf.cover && (
                  <>
                    {' '}
                    <button className="btn-mu-source" onClick={() => { shelf.setCover(null); setCoverError(null); }}>
                      Use the banner
                    </button>
                  </>
                )}
              </p>
              {coverError && <p className="option-reason" role="alert">{coverError}</p>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

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
  shelf = null,
  onAddToShelf,
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
        {shelf && <ShelfOption shelf={shelf} onClick={onAddToShelf} />}
        <MeleeUnlockedCard />
      </div>
    </div>
  );
};

export default ExportHome;
