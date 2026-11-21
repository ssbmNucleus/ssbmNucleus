export { TrashIcon } from '../../shared/ui/Icons'

export const PlusIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="12" y1="5" x2="12" y2="19"/>
    <line x1="5" y1="12" x2="19" y2="12"/>
  </svg>
)

export const ImportIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="7 10 12 15 17 10"/>
    <line x1="12" y1="15" x2="12" y2="3"/>
  </svg>
)

// Icon for laser extra type
const LaserIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="2" y1="12" x2="22" y2="12" strokeLinecap="round" />
    <circle cx="12" cy="12" r="2" fill="currentColor" />
    <path d="M4 8l2 4-2 4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M20 8l-2 4 2 4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// Icon for side-B extra type (afterimage/dash effect)
const SideBIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 12h4M9 12h4M14 12h4" strokeLinecap="round" opacity="0.3" />
    <path d="M18 12h4" strokeLinecap="round" />
    <path d="M20 8l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// Icon for up-B extra type (Firefox/Firebird flame)
const UpBIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 22c-4 0-7-3-7-7 0-2 1-4 2-5 0 2 1 3 2 3 0-3 2-6 3-8 1 2 3 5 3 8 1 0 2-1 2-3 1 1 2 3 2 5 0 4-3 7-7 7z" strokeLinejoin="round" />
    <path d="M12 22v-5" strokeLinecap="round" />
  </svg>
)

// Icon for shine (reflector/down-B)
const ShineIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="12,2 15,9 22,9 17,14 19,22 12,17 5,22 7,14 2,9 9,9" strokeLinejoin="round" />
  </svg>
)

// Icon for laser ring effect
const LaserRingIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="4" />
    <line x1="12" y1="2" x2="12" y2="6" strokeLinecap="round" />
    <line x1="12" y1="18" x2="12" y2="22" strokeLinecap="round" />
    <line x1="2" y1="12" x2="6" y2="12" strokeLinecap="round" />
    <line x1="18" y1="12" x2="22" y2="12" strokeLinecap="round" />
  </svg>
)

// Icon for sword trail
const SwordIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M14.5 4L20 9.5 9.5 20H4v-5.5L14.5 4z" strokeLinejoin="round" />
    <path d="M16 2l6 6" strokeLinecap="round" />
    <path d="M4 20l3-3" strokeLinecap="round" />
  </svg>
)

// Icon for punch effects (Falcon Punch, Warlock Punch)
const PunchIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="8" />
    <path d="M12 4v4M12 16v4M4 12h4M16 12h4" strokeLinecap="round" />
    <circle cx="12" cy="12" r="3" fill="currentColor" opacity="0.5" />
  </svg>
)

// Icon for thunder effects (Pikachu/Pichu Thunder, PK Thunder)
const ThunderIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinejoin="round" />
  </svg>
)

// Icon for fireball effects (Mario/Luigi)
const FireballIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="6" />
    <path d="M12 6c-2 0-3 2-3 3s1 2 3 2 3-1 3-2-1-3-3-3z" fill="currentColor" opacity="0.3" />
    <circle cx="12" cy="12" r="2" fill="currentColor" />
  </svg>
)

// Icon for shadow ball (Mewtwo)
const ShadowBallIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="5" opacity="0.5" />
    <circle cx="12" cy="12" r="2" fill="currentColor" />
  </svg>
)

// Icon for gun model (blaster)
const GunIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 14h10l4-4h2v4l-2 2H4z" strokeLinejoin="round" />
    <path d="M6 14v4h2v-4" strokeLinejoin="round" />
    <circle cx="16" cy="10" r="1" fill="currentColor" />
  </svg>
)

export const EffectIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
  </svg>
)

export const ICONS = {
  laser: LaserIcon,
  sideb: SideBIcon,
  upb: UpBIcon,
  shine: ShineIcon,
  laser_ring: LaserRingIcon,
  sword: SwordIcon,
  punch: PunchIcon,
  thunder: ThunderIcon,
  fireball: FireballIcon,
  shadowball: ShadowBallIcon,
  gun: GunIcon,
  effect: EffectIcon
}
