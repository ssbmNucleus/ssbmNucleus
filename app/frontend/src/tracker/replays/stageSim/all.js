// The stage simulators that are DRAWN, registered once. Imported for its
// side effect by liteStageInference.js. A stage joins this file only once its
// RNG anchor and tested collision paths are supported; unsupported interaction
// paths still return null.
import { registerDefaultStageSim as registerStageSim } from './index.js'
import stage2 from './stage2.js'
import stage3 from './stage3.js'
import stage4 from './stage4.js'
import stage5 from './stage5.js'
import stage6 from './stage6.js'
import stage7 from './stage7.js'
import stage9 from './stage9.js'
import stage10 from './stage10.js'
import stage11 from './stage11.js'
import stage13 from './stage13.js'
import stage15 from './stage15.js'
import stage16 from './stage16.js'
import stage17 from './stage17.js'
import stage18 from './stage18.js'
import stage19 from './stage19.js'
import stage20 from './stage20.js'
import stage22 from './stage22.js'
import stage24 from './stage24.js'
import stage25 from './stage25.js'
import stage27 from './stage27.js'
import stage29 from './stage29.js'

// Event-free exact event timelines: FoD 25/25, Stadium 20/20 real games.
// Recorded stage events remain authoritative; input-tail coverage is bounded
// by rngInputTails.json and Stadium's unmodeled jumbotron view changes.
registerStageSim(2, stage2)
registerStageSim(3, stage3)
// C23/C26: source-ordered switch RNG and replay material/Bill inputs;
// floor callbacks include leaders and followers of every vanilla character.
// C33: full Bob-omb/Saturn captures retain 100% emitted-exact coverage.
registerStageSim(4, stage4)
// C28: five Kongo captures pass fully, including independent Nana landings
// and her copied Squall Hammer contact. Item-enabled crates fail closed.
registerStageSim(5, stage5)
// C29: replay camera, source-ordered flybys and cannon damage/destruction;
// all ten captures emit fully and pass. Uncertified damage histories gate.
registerStageSim(7, stage7)
// C28: awnings, roof collapse/recovery, Nana and ice-article landings are
// integrated. Both captures emit fully; ambient RNG precedes recovery RNG.
registerStageSim(9, stage9)
// Mute City's collision is scripted (the track spline), not seed-driven.
registerStageSim(10, stage10)
// C20: all five Cruise captures pass (55,126 complete paired frames).
// Source spline/contact/visibility composition; donut RNG precedes wind.
// C26: shared vanilla weights include transforms and Nana's floor callbacks.
registerStageSim(11, stage11)
// C16: Slippi frame = dump match_frame. Every complete paired frame in all
// available dumps passes exact visibility/flags and the 0.05-unit geometry
// gate. Float interpolation is not bit-exact; REPORT.md gives both counts.
// Truncated final frames without a raw Frame Bookend are reported separately.
// Turtle: priority 4 current-frame cursor; Tingle follows recorded item state.
// C26: raft callbacks use shared fighter weights, including Nana; items gate.
registerStageSim(13, stage13)
// Kraid, blocks, crane/helicopter/UFO, scroll and Flat Zone use source-ordered
// setup/current-frame cursors. Unsupported histories still return null.
registerStageSim(15, stage15)
// C28/C32: normal block destruction/respawn is integrated, including Nana and
// hidden-Blizzard bounds. Missing fighter poses/ECBs, bombs and uncertain
// falling-block callbacks gate. See c28/REPORT.md for the C27 data handoff.
// C33: normal histories pass; cap-hidden injected common items remain gated.
registerStageSim(17, stage17)
// C28: all three Fourside captures emit fully, including Nana roof triggers.
registerStageSim(18, stage18)
// C23/C26: shared attacks/ECBs/weights drive blocks and pulleys. Ceiling
// callbacks precede all hit sparks, then source-ordered damage callbacks.
// StopCeil's two map passes are counted; ambiguous return clearance gates
// only uncertain rows when later clearance proves that simulation can resume.
// Grounded pulley contacts retain mpLib's .1-unit endpoint tolerance.
// C30: recorded and cap-hidden fireballs, Shadow Ball, Chef, needles, Ness
// and Pikachu articles join C27's families in the default material path.
// Deferred effects precede priority-13 sparks and priority-14 respawns.
// C32: constrained chain/tether, PK Thunder trails and copied/common item
// attacks join the default path. Missing identities/poses still fail closed.
// C33 integrates copied article births/restoration and Shadow Ball corner
// explosions. Every emitted frame passes; c33/REPORT.md lists coverage/nulls.
registerStageSim(19, stage19)
registerStageSim(25, stage25)
registerStageSim(27, stage27)
// Neither Yoshi stage's collision callbacks consume RNG. Stage 16's tested
// shared vanilla attacks and both StopCeil callbacks drive break/return.
// C30 adds charged flight attacks, grip histories, article map/terminal
// hits and unrecorded birth-frame Jolts. C32 adds constrained chain/tether,
// PK Thunder trails, copied articles and authored block restoration poses.
// C17: Stage 29 passes all four captures bit-exactly, including the left
// cloud's loading, vanish, return and spring-back cycle.
registerStageSim(16, stage16) // C33: copied articles and active Samus are certified.
registerStageSim(29, stage29)

// Fail-closed registrations: every emitted frame on every capture passes the
// gate; unsupported histories return null and keep the base renderer.
// 20: C17 setup/carpet/Pidgit path; C21 pass6 Birdo capture exact until the
// damaged Birdo (state>=8) at 8178, then null.
registerStageSim(20, stage20)
// C25/C26: shared fighter attacks, including simultaneous Nana hits, drive
// support break/restore and connector dynamics. C27 adds item hit capsules,
// charged damage and source-proven turnip rolls. C30 includes Yoyo/Missile/
// Skull Bash histories. C32 verifies charged support hits and Bob-omb/Saturn
// damage, including explosion hitlag and post-collision state changes.
// Ground callbacks follow GObj creation order: parent left before nested right.
// C33: all 33 captures emit fully, including all eight full Kirby copies.
registerStageSim(6, stage6)
// C22: authored FObj start offsets fixed; all four Venom captures pass.
registerStageSim(22, stage22)
// C22: full road/car/platform pipeline and contacts, 46,730/46,730 frames.
// Common-item pools and uncertified ledge histories fail closed.
registerStageSim(24, stage24)
