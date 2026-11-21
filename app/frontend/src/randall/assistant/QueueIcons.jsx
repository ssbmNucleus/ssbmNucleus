// Copied from Ozone src/components/logos.tsx.
export function QueueIcon({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <path d="M 3 4.5 h 10" />
        <path d="M 3 8 h 10" />
        <path d="M 3 11.5 h 6.5" />
      </g>
    </svg>
  );
}

/** The return/enter corner arrow (↵) that fronts the Steer action. */
export function SteerReturnIcon({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M 13 4 v 3.2 a 2 2 0 0 1 -2 2 H 5" />
        <path d="M 7.5 6.8 L 4.5 9.2 L 7.5 11.6" />
      </g>
    </svg>
  );
}

/** A trash can, for removing a queued prompt. */
export function TrashIcon({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M 3 4.5 h 10" />
        <path d="M 6.2 4.5 V 3.6 a 1 1 0 0 1 1 -1 h 1.6 a 1 1 0 0 1 1 1 v 0.9" />
        <path d="M 4.4 4.5 l 0.55 8 a 1.2 1.2 0 0 0 1.2 1.1 h 3.7 a 1.2 1.2 0 0 0 1.2 -1.1 l 0.55 -8" />
        <path d="M 6.7 7 v 4" />
        <path d="M 9.3 7 v 4" />
      </g>
    </svg>
  );
}

/** A horizontal ellipsis (⋯) — the overflow-menu affordance. */
export function MoreIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <g fill="currentColor">
        <circle cx="3.5" cy="8" r="1.3" />
        <circle cx="8" cy="8" r="1.3" />
        <circle cx="12.5" cy="8" r="1.3" />
      </g>
    </svg>
  );
}

