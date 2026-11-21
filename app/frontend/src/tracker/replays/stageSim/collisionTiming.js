// NTSC 1.02, paths relative to the melee decomp. A collision lag measures
// completed game frames from a callback's joint/vertex WRITE to the collision
// refresh. It is not an offset between a RAM dump's counter and Slippi events.
//
// ground.c:933-934,989-1008: animation runs at priority 1; stage callbacks at 4.
// ground.c:1676-1726: Ground_UpdateMapColl calls mpLib_80055E9C synchronously.
// mplib.c:4856-4918,4940-4943,5036: that call sets up the CURRENT joint matrix,
// writes CollVtx.pos, and updates dynamic line kinds. No deferred vertex queue.
// inlines.h:48-52: Ground_UpdateWindAndMapColl includes the same refresh.
//
// grAnime_801C8138 (granime.c:983-1042) requests AND evaluates frame 0, so
// switching that animation in priority 4 is visible in that frame. By contrast,
// grAnime_801C7B24/801C7FF8 request without evaluation (granime.c:828-951): their
// first animated pose arrives in the next priority-1 pass. Model that pending
// animation request in the state machine; do not delay all collision or RNG.
export const COLLISION_TIMING = Object.freeze({
  2: Object.freeze({collisionLag:0,priority:4,source:'grizumi.c:532-559: set joint Y, then mpLib_80055E9C'}),
  6: Object.freeze({collisionLag:0,priority:4,source:'grzebes.c:627-645: mpVtxSetPos / mpLib_80055E24; support refresh at 730'}),
  7: Object.freeze({collisionLag:0,priority:4,source:'grcorneria.c:709-730: drift, cannon, scheduler, then Ground_UpdateMapColl'}),
  13: Object.freeze({collisionLag:0,priority:4,source:'grgreatbay.c:423-583: evaluate animation/set joints, then Ground_UpdateMapColl; Tingle priority 5 at 251, refresh 707-712'}),
  15: Object.freeze({collisionLag:0,priority:4,source:'grkraid.c:249-265: AddRotationZ then Ground_UpdateWindAndMapColl; actor hit affects the earlier map object on its next proc'}),
  17: Object.freeze({collisionLag:0,priority:4,source:'grgreens.c:763-766: 802166C4 updates/spawns blocks, then Ground_UpdateMapColl; joint writes 1303-1308'}),
  18: Object.freeze({collisionLag:0,priority:4,source:'grfourside.c:473-485,537-541,610: crane/UFO refresh in callback; crane ReqAnim is separately pending one animation pass'}),
  22: Object.freeze({collisionLag:0,priority:4,source:'grvenom.c:745-746,1279-1297: scheduler and current collision proxy refresh; environment starts at 478 and toggles joint 2 at 894-907; inlines.h:156-179 reads the linked model pose'}),
  24: Object.freeze({collisionLag:0,priority:4,source:'grbigblue.c:682,1282,1917,2244: explicit Ground_UpdateMapColl calls; object-local write order still needs integration'}),
  25: Object.freeze({collisionLag:0,priority:4,source:'gricemt.c:932,993,1046,1112,1163,1218: scroll then Ground_UpdateMapColl; field swaps refresh 1735-1737,1781-1783'}),
  27: Object.freeze({collisionLag:0,priority:4,source:'grflatzone.c:363-368: grAnime_801C8138 immediately evaluates selected animation, then Ground_UpdateMapColl'}),
})
