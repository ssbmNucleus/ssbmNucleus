/**
 * ProjectHeaderInfo - left side of the install-page header. Shows the disc banner
 * thumbnail plus the long name / long maker as read-only text. Clicking the
 * banner (pencil on hover) opens the full BuildInfoModal, which is where every
 * field (names, makers, image, description) is edited.
 *
 * The long name defaults to the project (folder) name when unset.
 */
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { rgbaToDataUrl } from './banner'

export default function ProjectHeaderInfo({ buildInfo, projectName, onOpenBanner }) {
  const longName = buildInfo?.longName || projectName || ''
  const longMaker = buildInfo?.longMaker || ''

  const bannerSrc = buildInfo
    ? rgbaToDataUrl(buildInfo.bannerRgbaBase64, buildInfo.bannerWidth, buildInfo.bannerHeight)
    : null

  return (
    <div className="mex-build-header">
      <span className="status-dot" />

      <button
        type="button"
        className="mex-banner-thumb"
        title="Edit banner & info"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('start'); onOpenBanner() }}
      >
        {bannerSrc ? (
          <img src={bannerSrc} alt="Banner" />
        ) : (
          <span className="mex-banner-thumb__empty">banner</span>
        )}
        <span className="mex-banner-thumb__pencil">✎</span>
      </button>

      <div className="mex-build-fields">
        <span className="mex-inline-input mex-inline-input--name" title={longName}>
          {longName}
        </span>
        {longMaker && (
          <span className="mex-inline-input mex-inline-input--maker" title={longMaker}>
            {longMaker}
          </span>
        )}
      </div>
    </div>
  )
}
