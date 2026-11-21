import { effectOverviewSrc } from './pictograms.js'

const BASE = './extras/references/'
const shot = (file, viewBox, caption, details = {}) => ({ src: `${BASE}${file}.png`, viewBox, caption, ...details })
const flight = details => shot('fox-flight', '410 260 630 700', 'Fox Up-B · flight · example colors', details)
const beam = details => shot('fox-laser', '800 340 424 290', 'Fox laser · example colors', { pinSize: 12, ...details })
const sword = details => shot('marth-sword', '650 165 480 475', 'Marth sword trail · example colors', details)

// Coordinates are in the unchanged source captures. Outlines identify human
// elements, never pretend that two color operands have separate anatomy.
export const EFFECT_REFERENCES = {
  shine: {
    shield: shot('fox-shine', '390 235 475 610', 'Fox Shine · pink band with a green edge', {
      point: [704, 536], outline: 'M607 404 L739 479 L739 634 L607 709 L474 634 L474 479 Z M607 478 L678 516 L678 598 L607 639 L535 598 L535 516 Z',
    }),
    sparkles: shot('fox-shine', '390 235 475 610', 'Sparkles shown in green around the shield', { point: [799, 300] }),
    flash: shot('fox-shine-flash', '355 225 470 510', 'Startup flash · bright core and outer tint', { point: [575, 412] }),
  },
  upb: {
    startup: shot('fox-startup', '330 140 620 590', 'Fox Up-B · startup · rings shown in pink', {
      point: [540, 610], outline: 'M505 650 L475 385 L515 205 L750 205 L785 655 Z',
    }),
    main_flame: flight({ point: [820, 465], outline: 'M475 710 Q455 485 665 290 Q825 245 960 665' }),
    flight_puffs: flight({ point: [688, 852], outline: 'M535 735 Q655 680 770 735 L785 955 L520 955 Z' }),
    travel_sparkles: flight({ point: [833, 828] }),
  },
  charge_flames: {
    Flame: shot('fox-charge-flames', '425 75 460 610', 'Broad flame puffs shown in cyan', { point: [589, 500] }),
    Wisp: shot('fox-charge-wisps', '425 75 460 610', 'Thin rising wisps shown in green', { point: [726, 205] }),
  },
  upb_charge_fire: { '*': flight({ point: [688, 852] }) },
  screw_attack: {
    Arc: shot('samus-arcs', '470 375 450 370', 'Brief electrical arcs shown in green', { point: [821, 501], outline: 'M732 455 L857 440 L897 535 L757 590 Z' }),
    'Warm Swirl': shot('samus-swirl', '445 340 400 380', 'Rotating swirl shown in green and purple', { point: [530, 560] }),
  },
  laser: {
    wide: beam({ point: [1120, 414], outline: 'M830 486 L944 375 L1224 375 M830 486 L944 598 L1224 598' }),
    thin: beam({ point: [1170, 462], outline: 'M850 486 L988 455 L1224 455 M850 486 L988 519 L1224 519' }),
    outline: beam({ point: [1008, 478] }),
    center: beam({ point: [1100, 487] }),
    tip: beam({ point: [877, 486] }),
  },
  sword: {
    inner: sword({ point: [963, 502], outline: 'M915 575 L998 407 Q952 323 845 260' }),
    outer: sword({ point: [1049, 442], outline: 'M1032 575 L1080 343 Q1016 238 904 208' }),
  },
  sideb: { '*': shot('fox-afterimage', '56 365 745 335', 'Fox Side-B · afterimage shown in blue', { outline: 'M62 420 Q210 363 316 430 L317 644 L70 659 Z' }) },
  laser_ring: { '*': shot('fox-muzzle', '470 220 350 520', 'Fox blaster · streak burst shown in pink', { outline: 'M640 230 L789 295 L783 674 L644 720 Z' }) },
  upb_texture: { '*': flight({}) },
  kirby_copy_mario: { '*': shot('kirby-fireball', '260 400 490 265', 'Kirby’s copied fireball · example colors') },
  kirby_copy_luigi: { '*': shot('kirby-smoke', '320 380 450 260', 'Kirby’s copied fireball · trailing smoke shown in pink') },
  kirby_copy_bowser: { '*': shot('kirby-breath', '265 340 460 340', 'Kirby’s copied fire breath · example colors') },
  kirby_copy_iceclimbers: { '*': shot('kirby-ice', '250 350 535 335', 'Kirby’s ice shot · particles shown in pink') },
}

export function effectReference(effectId, part, character) {
  const mapped = EFFECT_REFERENCES[effectId]?.[part.id] || EFFECT_REFERENCES[effectId]?.['*']
  if (mapped) return mapped
  const donor = { kirby_copy_ganon: ['warlock_punch', 'Ganondorf’s Warlock Punch'],
    punch_texture: ['falcon_punch', 'Falcon Punch'], breath_texture: ['bowser_fire_breath', 'Bowser’s fire breath'] }[effectId]
  if (donor) return { src: effectOverviewSrc(donor[0]), caption: `${donor[1]} · effect reference` }
  const keys = part.controls?.flatMap(control => control.keys || [control.key]) || [part.id]
  const src = part.picto?.endsWith('.png') ? part.picto : effectOverviewSrc(effectId, keys)
  return src ? { src, caption: 'In-game reference · several parts may appear together' } : null
}
