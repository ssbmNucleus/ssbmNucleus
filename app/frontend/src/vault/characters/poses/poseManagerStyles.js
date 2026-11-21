/**
 * Styles for the Pose Manager modal (rendered via a <style> tag).
 *
 * Single source of truth for all pm-* classes — uses the app's design tokens
 * so the modal matches the rest of the UI (the old version hardcoded its own
 * dark-purple palette and fought a duplicate pm-* block in StorageViewer.css).
 */
export const POSE_MANAGER_STYLES = `
        .pm-overlay {
          position: absolute;
          inset: 0;
          background: rgba(6, 12, 20, 0.92);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: calc(var(--z-modal) + 40);
          padding: var(--page-block-padding) var(--modal-inline-padding);
          overflow: auto;
          overscroll-behavior: contain;
        }

        .pm-modal {
          width: min(100%, var(--modal-max-width));
          background: linear-gradient(
            165deg,
            var(--color-bg-elevated) 0%,
            var(--color-bg-base) 40%,
            var(--color-bg-deep) 100%
          );
          border: 1px solid var(--color-cyan);
          border-radius: var(--radius-2xl);
          box-shadow:
            var(--shadow-xl),
            0 0 80px rgba(0, 0, 0, 0.5),
            0 0 24px rgba(125, 211, 232, 0.12);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          margin: auto;
        }

        .pm-modal--create {
          height: min(100%, var(--modal-max-height));
        }

        .pm-modal--library {
          max-height: min(100%, var(--modal-max-height));
        }

        /* Header */
        .pm-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-bottom: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .pm-title {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          min-width: 0;
        }

        .pm-title-label {
          font-family: var(--font-display);
          font-size: var(--text-lg);
          font-weight: var(--font-bold);
          letter-spacing: var(--tracking-tight);
          background: var(--gradient-cyan);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .pm-title-char {
          font-size: var(--text-sm);
          color: var(--color-text-secondary);
          padding: 2px 10px;
          background: var(--color-bg-surface);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-md);
        }

        .pm-back-btn {
          display: inline-flex;
          align-items: center;
          gap: var(--space-1);
          padding: var(--space-1) var(--space-3);
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          color: var(--color-text-secondary);
          font-family: var(--font-display);
          font-size: var(--text-sm);
          font-weight: var(--font-semibold);
          cursor: pointer;
          transition: all var(--transition-fast);
          white-space: nowrap;
        }

        .pm-back-btn:hover {
          background: var(--color-cyan);
          border-color: var(--color-cyan);
          color: var(--color-bg-deep);
        }

        .pm-close-btn {
          width: 32px;
          height: 32px;
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-full);
          background: var(--color-bg-surface);
          color: var(--color-text-tertiary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all var(--transition-fast);
          flex-shrink: 0;
        }

        .pm-close-btn:hover {
          background: var(--color-danger-muted);
          color: var(--color-danger);
          border-color: var(--color-danger);
          transform: rotate(90deg);
        }

        /* ── Library view ─────────────────────────── */
        .pm-library {
          flex: 1;
          min-height: 12rem;
          overflow-y: auto;
          padding: var(--space-4) var(--space-6) var(--space-6);
          display: flex;
          flex-direction: column;
          gap: var(--space-3);
        }

        .pm-library-hint {
          font-size: var(--text-xs);
          color: var(--color-text-muted);
        }

        .pm-library-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
          gap: var(--space-3);
          align-content: start;
        }

        .pm-library-empty {
          grid-column: 1 / -1;
          text-align: center;
          color: var(--color-text-muted);
          font-size: var(--text-sm);
          padding: var(--space-6);
        }

        /* Same card shape as a pose (136:188 image + name bar), dashed */
        .pm-create-card {
          background: var(--color-bg-surface);
          border: 2px dashed var(--color-border-subtle);
          color: var(--color-text-tertiary);
          cursor: pointer;
        }

        .pm-create-card .pm-create-image {
          display: flex;
          align-items: center;
          justify-content: center;
          background: transparent;
        }

        .pm-create-card .pm-pose-name {
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: inherit;
        }

        .pm-create-card:hover {
          border-color: var(--color-cyan);
          background: var(--color-bg-deep);
          color: var(--color-cyan);
        }

        .pm-create-icon {
          font-size: 2rem;
          line-height: 1;
          font-weight: var(--font-regular);
        }

        /* Built-in pose card: a regular pose card with a "Built in" tag and no
           edit/delete controls. */
        .pm-pose-builtin {
          position: absolute;
          top: 4px;
          left: 4px;
          padding: 2px 6px;
          background: rgba(6, 12, 20, 0.8);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-muted);
          font-size: var(--text-xs);
          line-height: 1.2;
          pointer-events: none;
        }

        .pm-pose-card {
          display: flex;
          flex-direction: column;
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          overflow: hidden;
          transition: all var(--transition-fast);
        }

        .pm-pose-card:hover {
          border-color: var(--color-cyan);
          transform: translateY(-2px);
          box-shadow: var(--glow-cyan-sm);
        }

        .pm-pose-card.is-default {
          border-color: var(--color-teal);
          box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.22);
        }

        .pm-pose-image {
          position: relative;
          aspect-ratio: 136 / 188;
          background: var(--color-bg-base);
          overflow: hidden;
        }

        .pm-pose-image img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .pm-pose-placeholder {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: var(--font-display);
          font-size: var(--text-2xl);
          font-weight: var(--font-bold);
          color: var(--color-text-tertiary);
          background: linear-gradient(135deg, var(--color-bg-surface) 0%, var(--color-bg-deep) 100%);
        }

        .pm-pose-delete {
          position: absolute;
          top: 4px;
          right: 4px;
          width: 24px;
          height: 24px;
          background: rgba(6, 12, 20, 0.8);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-secondary);
          cursor: pointer;
          opacity: 0;
          transition: all var(--transition-fast);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .pm-pose-card:hover .pm-pose-delete {
          opacity: 1;
        }

        .pm-pose-delete:hover {
          background: var(--color-danger);
          border-color: var(--color-danger);
          color: white;
        }

        .pm-pose-edit {
          position: absolute;
          top: 4px;
          right: 32px;
          width: 24px;
          height: 24px;
          background: rgba(6, 12, 20, 0.8);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-secondary);
          cursor: pointer;
          opacity: 0;
          transition: all var(--transition-fast);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
        }

        .pm-pose-card:hover .pm-pose-edit {
          opacity: 1;
        }

        .pm-pose-edit:hover {
          background: var(--color-accent, #4a9eff);
          border-color: var(--color-accent, #4a9eff);
          color: white;
        }

        .pm-pose-default {
          position: absolute;
          left: 4px;
          bottom: 4px;
          padding: 3px 7px;
          background: rgba(13, 148, 136, 0.9);
          border: 1px solid var(--color-teal);
          border-radius: var(--radius-sm);
          color: white;
          font-size: 10px;
          font-weight: var(--font-bold);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          pointer-events: none;
        }

        .pm-pose-set-default {
          position: absolute;
          left: 4px;
          right: 4px;
          bottom: 4px;
          min-height: 26px;
          padding: 4px 6px;
          background: rgba(6, 12, 20, 0.86);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-secondary);
          cursor: pointer;
          opacity: 0;
          transition: all var(--transition-fast);
          font-size: 10px;
          font-weight: var(--font-bold);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }

        .pm-pose-card:hover .pm-pose-set-default {
          opacity: 1;
        }

        .pm-pose-set-default:hover {
          background: var(--color-teal);
          border-color: var(--color-teal);
          color: var(--color-bg-deep);
        }

        .pm-pose-set-default:disabled {
          cursor: progress;
          opacity: 0.75;
        }

        /* Row holding the left model picker + the viewer */
        .pm-create-row {
          flex: 1;
          display: flex;
          gap: var(--space-2);
          min-height: 0;
          align-items: stretch;
        }

        /* Left column. The native HSD render window overlays the viewport, so
           the model popup stays to the LEFT of it, never over it. */
        .pm-model-select {
          position: relative;
          flex: 0 0 220px;
          align-self: flex-start;
          display: flex;
          flex-direction: column;
          align-items: stretch;
          gap: 4px;
          padding-top: var(--space-1);
          font-size: 13px;
          color: var(--color-text-secondary);
        }

        .pm-model-menu-btn {
          width: 100%;
          background: var(--color-bg-elevated, rgba(6, 12, 20, 0.8));
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-primary);
          padding: 5px 8px;
          text-align: left;
          cursor: pointer;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          transition:
            border-color var(--transition-fast),
            color var(--transition-fast);
        }

        .pm-model-menu-btn:hover,
        .pm-model-menu-btn.active {
          border-color: var(--color-accent, #4a9eff);
          color: var(--color-accent, #4a9eff);
        }

        .pm-model-popover {
          position: absolute;
          top: calc(100% + 6px);
          left: 0;
          z-index: 70;
          width: 100%;
          max-height: min(420px, 62vh);
          overflow: auto;
          padding: 8px;
          background: var(--color-bg-deep, #090d13);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-md);
          box-shadow: 0 14px 34px rgba(0, 0, 0, 0.45);
        }

        .pm-model-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 7px;
        }

        .pm-model-card {
          min-width: 0;
          overflow: hidden;
          padding: 0;
          background: var(--color-bg-elevated, rgba(6, 12, 20, 0.8));
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-primary);
          cursor: pointer;
          text-align: left;
          transition:
            border-color var(--transition-fast),
            transform var(--transition-fast);
        }

        .pm-model-card:hover,
        .pm-model-card.active {
          border-color: var(--color-accent, #4a9eff);
        }

        .pm-model-card:hover {
          transform: translateY(-1px);
        }

        .pm-model-card-image {
          display: flex;
          align-items: center;
          justify-content: center;
          aspect-ratio: 136 / 188;
          background: var(--color-bg-deep);
          color: var(--color-text-tertiary);
          font-size: 20px;
          font-weight: 700;
        }

        .pm-model-card-image img {
          width: 100%;
          height: 100%;
          object-fit: contain;
          image-rendering: pixelated;
        }

        .pm-model-card-info {
          display: flex;
          align-items: center;
          min-width: 0;
          gap: 4px;
          padding: 5px;
          color: var(--color-text-secondary);
          font-size: 11px;
        }

        .pm-model-card-info span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .pm-model-stock {
          width: 18px;
          height: 18px;
          flex-shrink: 0;
          image-rendering: pixelated;
        }

        .pm-startfrom-tag {
          color: var(--color-text-tertiary, #8a97a8);
          font-style: italic;
        }

        .pm-pose-name {
          padding: var(--space-1) var(--space-2);
          font-family: var(--font-display);
          font-size: var(--text-xs);
          color: var(--color-text-secondary);
          text-align: center;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* ── Create view ──────────────────────────── */
        .pm-body {
          flex: 1;
          display: flex;
          gap: var(--space-3);
          padding: var(--space-3);
          min-height: 0;
          align-items: stretch;
        }

        .pm-left-section {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }

        .pm-viewer-section {
          flex: 1;
          position: relative;
          overflow: hidden;
          /* Never let the embedded native viewer collapse on short windows */
          min-height: clamp(180px, 38vh, 320px);
          min-width: 240px;
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
        }

        /* Embedded viewer fills the section (override its modal chrome) */
        .pm-viewer-section .mv-overlay {
          position: absolute !important;
          inset: 0 !important;
          width: 100% !important;
          height: 100% !important;
          padding: 0 !important;
          margin: 0 !important;
          overflow: hidden !important;
          background: transparent !important;
          backdrop-filter: none !important;
          z-index: 1 !important;
          animation: none !important;
        }

        .pm-viewer-section .mv-container {
          width: 100% !important;
          height: 100% !important;
          max-width: none !important;
          max-height: none !important;
          aspect-ratio: auto !important;
          border-radius: 0 !important;
          border: none !important;
          box-shadow: none !important;
          background:
            radial-gradient(ellipse at 50% 30%, rgba(125, 211, 232, 0.03) 0%, transparent 50%),
            linear-gradient(180deg, #0d1929 0%, #0a1420 100%) !important;
        }

        .pm-viewer-section .mv-header {
          display: none !important;
        }

        .pm-viewer-section .mv-body {
          flex: 1 !important;
          min-height: 0 !important;
          container-type: size;
        }

        /* At most 2:1. In portrait mode the viewer sizes the portrait frame by
           the view's width, so past about 2.27:1 the frame runs off the top and
           bottom and a new pose looked cropped tighter than the portrait it
           starts from (0.9.0 hand-check: the narrow-window layout, short windows). */
        .pm-viewer-section .mv-viewport {
          flex: 1 !important;
          width: auto !important;
          max-width: 200cqh !important;
          height: auto !important;
          aspect-ratio: auto !important;
          margin: 0 auto !important;
          border: none !important;
          border-radius: 0 !important;
          min-height: 0 !important;
          background: transparent !important;
        }

        .pm-viewer-section .mv-sidebar {
          display: none;
        }

        .pm-viewer-section .mv-controls {
          background: rgba(0, 0, 0, 0.5);
          border-top: 1px solid var(--color-border-subtle);
        }

        /* Category bar below viewer */
        .pm-category-bar {
          display: flex;
          flex-wrap: wrap;
          gap: var(--space-1);
          padding: var(--space-2);
          background: var(--color-bg-surface);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          flex-shrink: 0;
        }

        .pm-cat-btn {
          padding: 5px 10px;
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-secondary);
          font-size: var(--text-xs);
          cursor: pointer;
          transition: all var(--transition-fast);
        }

        .pm-cat-btn:hover {
          color: var(--color-text-primary);
          border-color: var(--color-border);
        }

        .pm-cat-btn.active {
          background: var(--gradient-cyan, var(--color-cyan));
          color: var(--color-bg-deep);
          border-color: var(--color-cyan);
        }

        /* Animation list panel */
        .pm-anim-section {
          width: 280px;
          min-width: 240px;
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          background: var(--color-bg-surface);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }

        .pm-anim-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: var(--space-2) var(--space-3);
          background: var(--color-bg-elevated);
          border-bottom: 1px solid var(--color-border-subtle);
          font-family: var(--font-display);
          font-size: var(--text-sm);
          font-weight: var(--font-semibold);
          color: var(--color-text-primary);
        }

        .pm-anim-count {
          background: var(--color-cyan);
          color: var(--color-bg-deep);
          padding: 2px 8px;
          border-radius: var(--radius-full);
          font-size: var(--text-xs);
          font-weight: var(--font-bold);
        }

        .pm-anim-filter {
          margin: var(--space-2);
          padding: var(--space-2);
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-sm);
          color: var(--color-text-primary);
          font-size: var(--text-sm);
        }

        .pm-anim-filter:focus {
          outline: none;
          border-color: var(--color-cyan);
        }

        .pm-anim-list {
          flex: 1;
          overflow-y: auto;
          padding: var(--space-1);
          min-height: 0;
        }

        .pm-anim-item {
          display: block;
          width: 100%;
          padding: var(--space-2);
          background: transparent;
          border: none;
          border-radius: var(--radius-sm);
          color: var(--color-text-secondary);
          font-size: var(--text-xs);
          text-align: left;
          cursor: pointer;
          transition: all var(--transition-fast);
        }

        .pm-anim-item:hover {
          background: var(--color-bg-elevated);
          color: var(--color-text-primary);
        }

        .pm-anim-item.active {
          background: var(--gradient-cyan, var(--color-cyan));
          color: var(--color-bg-deep);
        }

        /* Save controls */
        .pm-save-controls {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-top: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .pm-pose-name-input {
          flex: 1;
          min-width: 0;
          padding: var(--space-3) var(--space-4);
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          color: var(--color-text-primary);
          font-size: var(--text-sm);
          outline: none;
          transition: border-color var(--transition-fast);
        }

        .pm-pose-name-input:focus {
          border-color: var(--color-cyan);
        }

        .pm-pose-name-input::placeholder {
          color: var(--color-text-muted);
        }

        .pm-pose-name-input:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .pm-save-btn {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          padding: var(--space-3) var(--space-5);
          background: var(--gradient-cyan, var(--color-cyan));
          border: none;
          border-radius: var(--radius-lg);
          color: var(--color-bg-deep);
          font-family: var(--font-display);
          font-size: var(--text-sm);
          font-weight: var(--font-semibold);
          cursor: pointer;
          transition: all var(--transition-fast);
          white-space: nowrap;
        }

        .pm-save-btn:hover:not(:disabled) {
          box-shadow: var(--glow-cyan-sm);
          transform: translateY(-1px);
        }

        .pm-save-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* Status messages */
        .pm-message {
          padding: var(--space-2) var(--space-4);
          font-size: var(--text-sm);
          text-align: center;
          border-radius: var(--radius-md);
          flex-shrink: 0;
        }

        .pm-error {
          background: var(--color-danger-muted, rgba(220, 53, 69, 0.2));
          color: var(--color-danger, #ff6b6b);
          margin: 0 var(--space-6) var(--space-3);
        }

        .pm-success {
          background: var(--color-success-muted, rgba(40, 167, 69, 0.2));
          color: var(--color-success, #51cf66);
        }

        /* Narrow windows: stack the create view vertically */
        @media (max-width: 900px) {
          .pm-body {
            flex-direction: column;
            overflow-y: auto;
          }

          .pm-left-section {
            flex: 0 0 auto;
          }

          /* No native overlay on mobile/browser — stack the picker above. */
          .pm-create-row {
            flex-direction: column;
          }

          .pm-model-select {
            flex: 0 0 auto;
            align-self: stretch;
          }

          .pm-viewer-section {
            min-width: 0;
            height: clamp(180px, 40vh, 320px);
            flex: 0 0 auto;
          }

          .pm-anim-section {
            width: 100%;
            min-width: 0;
            flex: 0 0 auto;
            max-height: 16rem;
          }

          .pm-save-controls {
            padding: var(--space-3);
          }
        }
      `
