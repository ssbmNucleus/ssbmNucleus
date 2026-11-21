import HexagonLoader from './HexagonLoader';
import './ProgressPanel.css';

/**
 * Shared hexagon progress panel used by every long-running export step
 * (ISO build, auto texture pack, patch, bundle, in-game test).
 */
const ProgressPanel = ({
  title,
  label,
  progressValue = null,
  messageText,
  metaText = null,
  size = 120,
  className = '',
}) => (
  <div className={['export-progress', className].filter(Boolean).join(' ')}>
    <HexagonLoader
      className="progress-loader"
      size={size}
      label={label}
      progress={progressValue}
    />
    <div className="hexagon-progress-copy">
      <h3>{title}</h3>
      {metaText && <p className="hexagon-progress-meta">{metaText}</p>}
      <p className="progress-message">{messageText}</p>
    </div>
  </div>
);

export default ProgressPanel;
