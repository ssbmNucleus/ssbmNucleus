// Looks for the items that are not fighter projectiles: common items, Pokemon,
// and each stage's own objects. A hand-checked table of game facts, not a
// heuristic. Kinds are the decomp's ItemKind (it/forward.h).
//
// Size: every entry carries the item's ECB from its article (ItemAttr +0x40:
// up, down, front, back) and its model scale (+0x60), read from the vanilla
// ISO: ItCo.dat (common items, x8 character items, xC Pokemon) and each stage
// DAT's 'itemdata' list (stage items). mpColl_SetECBSource_Fixed makes the box
// y - down .. y + up and x - back .. x + front (mirrored when facing left),
// all times the scale (itmaplib.c). The look is Watch Lite's own simple
// picture over that box (litePaint.drawTableLook, itemArt.drawItemIcon).
//
// [name, scale, up, down, front, back, fill, shape?, alpha?]
// shape: 'ellipse' (default), 'rect', 'star', 'ring' (target/coin),
// 'shyguy', 'tingle', or a picture: 'capsule', 'bobomb', 'sword', 'bat',
// 'pokeball', 'tomato', 'heart', 'shell', 'crate', 'barrel', 'hammer',
// 'mushroom'. An entry with radius `r` instead of a box is noted.
export const HIDDEN = 'hidden'

const ITEMS = {
  // Common items (ItCo.dat common articles)
  0: ['Capsule', 1.05, 4.25, 3.38, 1.64, 1.64, '#e8e8f0', 'capsule'],
  1: ['Crate', 1, 7.5, 7.6, 7.5, 7.5, '#b98a4e', 'crate'],
  2: ['Barrel', 1, 7.8, 7.9, 7.2, 7.2, '#a0703c', 'barrel'],
  3: ['Egg', 1, 3, 3, 2.6, 2.6, '#f2efe4'],
  4: ['Party Ball', 0.9, 7, 7.5, 7, 7, '#ff9ad5'],
  5: ['Barrel Cannon', 1, 7.8, 7.9, 7.2, 7.2, '#8a5a2c', 'barrel'],
  6: ['Bob-omb', 0.78, 5, 5, 4, 4, '#3d4458', 'bobomb'],
  7: ['Mr. Saturn', 1.12, 2.5, 3, 3, 2.75, '#f0e6c8'],
  8: ['Heart Container', 1, 5.5, 5.5, 6.65, 6.65, '#ff5d8f', 'heart'],
  9: ['Maxim Tomato', 0.55, 5, 4.95, 6.3, 6.3, '#ff4d4d', 'tomato'],
  10: ['Starman', 1, 4.9, 4.1, 4.75, 4.75, '#ffe24d', 'star'],
  11: ['Home-Run Bat', 0.85, 6.7, 7.7, 0.65, 0.65, '#d8c8a0', 'bat'],
  12: ['Beam Sword', 1.2, 0, 5.85, 0.65, 0.65, '#9fe3ff', 'sword'],
  13: ['Parasol', 1, 7.4, 7.6, 6, 6, '#ff9ad5'],
  14: ['Green Shell', 0.74, 4, 4, 5.5, 5.5, '#3fc457', 'shell'],
  15: ['Red Shell', 0.74, 4, 4, 5.5, 5.5, '#ff4d4d', 'shell'],
  16: ['Ray Gun', 0.8, 2.8, 3, 4.4, 5.4, '#c0c8d8', 'rect'],
  17: ['Freezie', 1, 5.3, 3.9, 4.4, 4.4, '#9fe3ff'],
  18: ['Food', 0.8, 4.5, 0, 3.5, 3.5, '#ffb066'],
  19: ['Motion-Sensor Bomb', 0.8, 1.8, 2.8, 2, 2, '#ff6a6a'],
  20: ['Flipper', 1, 6.5, 7, 2.5, 2.5, '#6ea8ff', 'rect'],
  21: ['Super Scope', 1.03, 5, 5.5, 1.5, 2, '#c0c8d8', 'rect'],
  22: ['Star Rod', 1, 6, 6, 2.5, 2.5, '#ffe24d', 'rect'],
  23: ["Lip's Stick", 1, 5, 5, 2.5, 2.5, '#ff7ab8', 'rect'],
  24: ['Fan', 2, 3.5, 3.55, 1.3, 1.3, '#ff9ad5', 'rect'],
  25: ['Fire Flower', 1.05, 3, 3.8, 3, 3, '#ff7a2f'],
  26: ['Super Mushroom', 1.5, 2.2, 2.15, 2.5, 2.5, '#ff4d4d', 'mushroom'],
  27: ['Poison Mushroom', 1.5, 2.2, 2.15, 2.5, 2.5, '#9b6bff', 'mushroom'],
  28: ['Hammer', 1, 8.5, 8.5, 5, 5, '#d8b06a', 'hammer'],
  29: ['Warp Star', 1, 6, 6, 6, 6, '#ffe24d', 'star'],
  30: ['Screw Attack', 0.6, 4.5, 4.5, 4.5, 4.3, '#ff9a3d'],
  31: ['Bunny Hood', 1, 3, 4.2, 3, 3, '#f4f4ee'],
  32: ['Metal Box', 0.7, 5, 5.1, 5, 5, '#a8b0c0', 'rect'],
  33: ['Cloaking Device', 0.74, 3.3, 0.8, 4, 4, '#a8b0c0'],
  34: ['Poke Ball', 0.7, 3, 3.5, 3.9, 3, '#ff4d4d', 'pokeball'],
  35: ['Ray Gun shot', 1, 0.8, 1, 2.9, 3.6, '#ff5c5c', 'rect'],
  36: ['Star Rod star', 1.5, 3, 0, 3, 3, '#ffe24d', 'star'],
  37: ["Lip's Stick spore", 1, 3, 0, 3, 3, '#ff7ab8', 'ellipse', 0.6],
  38: ['Super Scope shot', 1, 2.8, 3, 1.5, 2.2, '#ff9a3d'],
  39: ['Ray Gun beam', 1, 3, 3, 3, 3, '#ff5c5c', 'ellipse', 0.6],
  40: ['Hammer head', 1, 3.75, 3.75, 5, 5, '#d8b06a', 'rect'],
  41: ['Fire Flower flame', 1, 3, 4.2, 3, 3, '#ff7a2f', 'ellipse', 0.7],
  42: ['Yoshi egg (event)', 1.3, 3, 3, 2.6, 2.6, '#f2efe4'],
  43: ['Goomba', 1.2, 6.5, 0, 5, 5, '#a0703c'],
  44: ['ReDead', 1.1, 20, 0, 4, 2, '#8a7a6a'],
  45: ['Octorok', 1, 12, 0, 7, 10, '#ff7a6a'],
  46: ['Ottosea', 0.8, 11, 0, 8, 8, '#6ea8ff'],
  47: ['Octorok stone', 1, 1, 1, 3, 3, '#a8b0c0'],
  // Yoshi's egg around a swallowed fighter (PlYs.dat / PlKbCpYs.dat; the
  // fighter inside is hidden, ftCo_YoshiEgg)
  87: ["Yoshi's egg", 2, 3, 3, 3, 3, '#e8f4dc'],
  157: ["Kirby's Yoshi egg", 2, 3, 3, 3, 3, '#e8f4dc'],
  // Kirby's spat star (PlKb.dat, It_Kind_Unk1, ftkirbyspecialn.c)
  52: ["Kirby's star", 1, 4, 0, 1, 1, '#ffe24d', 'star'],
  // Coin battle: the coins a hit fighter spills (ftcommon.c -> it_2E5A,
  // It_Kind_Unk4; ItCo.dat x8)
  158: ['Coin', 1, 3, 3, 3, 3, '#ffd34d', 'ring'],
  159: ['Coin', 1.3, 8, 1, 4, 4, '#ffd34d', 'ring'],
  // Pokemon (ItCo.dat xC) and what they make
  161: ['Goldeen', 2, 4, 0, 2, 2, '#ff8a5c'],
  162: ['Chikorita', 2.2, 4, 0, 2, 2, '#9fe07a'],
  163: ['Snorlax', 1.2, 20, 0, 10, 10, '#3f6a8a'],
  164: ['Blastoise', 1.3, 14, 0, 8, 6, '#5a8ad8'],
  165: ['Weezing', 1, 6, 0, 8, 8, '#9b6bff'],
  166: ['Charizard', 1.5, 18, 0, 10, 10, '#ff8a3d'],
  167: ['Moltres', 1.1, 16, 0, 10, 6, '#ff9a3d'],
  // Zapdos's ECB 'down' is -20 (a box wholly above it); drawn from its feet.
  168: ['Zapdos', 1.4, 18, 0, 8, 8, '#ffe24d'],
  169: ['Articuno', 1.4, 16, 0, 8, 8, '#9fe3ff'],
  170: ['Wobbuffet', 1.4, 16, 0, 8, 8, '#6ea8ff'],
  171: ['Scizor', 1.4, 8, 8, 2, 2, '#ff4d4d'],
  // Unown: no ECB; its model is picked at run time from 26 letters
  // (itunknown.c), the same as its swarm's: drawn as the swarm's hit sphere.
  172: ['Unown', 3, 5.47, 5.47, 5.47, 5.47, '#8a6ad8', 'ellipse', 0.3],
  173: ['Entei', 1.2, 18, 0, 12, 8, '#b06a3c'],
  174: ['Raikou', 1.4, 14, 0, 12, 8, '#ffd34d'],
  175: ['Suicune', 1.2, 14, 0, 10, 10, '#6ec8e8'],
  176: ['Bellossom', 2.6, 4, 0, 2, 2, '#9fe07a'],
  177: ['Electrode', 1.1, 16, 0, 8, 8, '#ff4d4d'],
  180: ['Ditto', 2.6, 4, 0, 2, 2, '#c8a0e0'],
  181: ['Clefairy', 2, 4, 0, 2, 2, '#ffb0c8'],
  182: ['Togepi', 4, 3, 0, 1.5, 1.5, '#f2efe4'],
  184: ['Celebi', 1.5, 16, 0, 8, 8, '#9fe07a'],
  185: ['Staryu', 1.8, 16, 0, 8, 8, '#d8a050'],
  186: ['Chansey', 1.4, 16, 0, 8, 8, '#ffb0c8'],
  187: ['Porygon2', 2.5, 5, 0, 8, 8, '#ff7a8a'],
  188: ['Cyndaquil', 2, 3, 0, 2, 2, '#3f6a8a'],
  189: ['Marill', 2, 4, 0, 2, 2, '#6ea8ff'],
  190: ['Venusaur', 0.9, 16, 0, 16, 8, '#5aa08a'],
  191: ["Chikorita's leaf", 1, 4, 0, 2, 2, '#9fe07a'],
  192: ["Blastoise's water", 1, 4, 0, 3, 3, '#6ea8ff', 'ellipse', 0.6],
  193: ["Weezing's gas", 1, 4, 0, 2, 2, '#9b6bff', 'ellipse', 0.4],
  194: ["Weezing's gas", 1, 4, 0, 2, 2, '#9b6bff', 'ellipse', 0.4],
  195: ["Charizard's fire", 1, 8, 0, 4, 4, '#ff8a3d', 'ellipse', 0.5],
  196: ["Charizard's fire", 1, 8, 0, 4, 4, '#ff8a3d', 'ellipse', 0.5],
  197: ["Charizard's fire", 1, 8, 0, 4, 4, '#ff8a3d', 'ellipse', 0.5],
  198: ["Charizard's fire", 1, 8, 0, 4, 4, '#ff8a3d', 'ellipse', 0.5],
  // An Unown of the swarm: no ECB; its hit sphere is 5.47 x scale 3.
  199: ['Unown swarm', 3, 5.47, 5.47, 5.47, 5.47, '#8a6ad8', 'ellipse', 0.3],
  203: ["Ho-Oh's fire", 3.7, 4, 0, 2, 2, '#ff8a3d', 'ellipse', 0.5],
  204: ["Staryu's star", 1, 4, 0, 2, 2, '#ffe24d', 'star'],
  205: ["Chansey's egg", 1, 3, 3, 2.6, 2.6, '#f2efe4'],
  206: ["Cyndaquil's fire", 1, 3, 3, 3, 3, '#ff8a3d', 'ellipse', 0.6],
  207: ['Pokemon effect', 1, 3, 3, 3, 3, '#c8a0e0', 'ellipse', 0.5],
  // Enemies and stage objects (each stage DAT's itemdata; GrTe.dat for the
  // ones only Adventure / Break the Targets uses)
  209: ['Target', 1, 4, 0, 2, 2, '#ff4d4d', 'ring'],
  210: ['Shy Guy', 0.85, 6, 6, 8, 8, '#e0483e', 'shyguy'],
  211: ['Koopa Troopa', 1.2, 6, 0, 10, 2, '#3fc457'],
  212: ['Koopa Paratroopa', 1.2, 6, 0, 10, 3, '#ff4d4d'],
  213: ['Like Like', 1.4, 12, 0, 8, 8, '#8a9a6a'],
  217: ['Polar Bear', 1, 26, 0, 9, 6, '#f4f4ee'],
  218: ['Klaptrap', 1, 16, 0, 8, 8, '#4f9d4a'],
  219: ['Green Shell', 1.2, 4.5, 0, 3, 3, '#3fc457', 'shell'],
  220: ['Red Shell', 1.2, 4, 0, 3, 3, '#ff4d4d', 'shell'],
  221: ['Tingle', 1, 20, 0, 8, 8, '#7bc96f', 'tingle'],
  225: ["Whispy's apple", 0.8, 4, 4, 4, 4, '#ff4d4d'],
  226: ["Whispy's healing apple", 0.8, 4, 4, 4, 4, '#7bc96f'],
  230: ['Flat Zone tool', 1, 4, 4, 3, 3, '#c8d0b8', 'rect'],
  233: ['Birdo', 1.2, 8, 8, 4, 4, '#ff8ab8'],
  236: ["Birdo's egg", 1.15, 3.5, 3.5, 3.5, 3.5, '#f4f0e8'],
}

// Held props drawn by their fighter's own pose (same rule as itemSizes.json's
// held flag; these two have no baked item table): Dr. Mario's cape (PlDr.dat)
// and Young Link's taunt milk (ftCl_Init.c).
const HELD = new Set([84, 123])

// The items each vanilla stage carries, as found in the owner's replays, by
// (stage, kind). Kind 160 is the ground "yaku" item: grMaterial_801C8CFC /
// 801C8D44 -> it_802E6AEC spawn it with kind 0xA0 on a stage joint or point.
// Its ItCo.dat article has no model (root joint NULL): it is the hit/hurt
// volume of a stage part. Where that part has collision the stage geometry
// already draws it, and the item is not drawn. Where the part is a model with
// no collision (Onett's cars, Mute City's cars, Jungle Japes' Klaptrap, Peach's
// Castle's Banzai Bill), the item is the only trace of a
// thing the game shows: it is drawn as that hazard's hit sphere, and only in
// an item state whose script (the stage DAT's ALDYakuAll[state], ground.c)
// has a hitbox, i.e. while the hazard is out. Every other stage item is its
// own kind (ITEMS above).
export const STAGE_ITEMS = {
  4: { 160: "Peach's Castle parts: Banzai Bill (state 3) and its blast (4) drawn; switch parts (1, 2) not" },
  5: { 218: 'Klaptrap' },
  6: { 160: 'hit volumes of the acid and the breakable floor pieces (grzebes.c): not drawn' },
  7: { 160: "the Great Fox gun's two hurt volumes (left/right_cannon): not drawn, the gun is collision",
       234: 'Arwing laser (drawn as a laser)', 235: 'Great Fox laser (drawn as a laser)' },
  8: { 210: 'Shy Guys' },
  9: { 160: 'the four cars (gronett.c car_items): drawn while driving through (states 2-5)' },
  10: { 160: 'the F-Zero cars, made while a car is within 200 units (grmutecity.c): drawn (state 2)' },
  12: { 160: "the Klaptrap jumping from the river (grgarden.c): drawn mid-jump (state 2)" },
  13: { 221: 'Tingle on his balloon' },
  16: { 160: "the nine flipper blocks' volumes (gryorster.c): not drawn, the blocks are collision" },
  17: { 160: 'block volumes (grgreens.c): not drawn, the blocks are collision',
        225: "Whispy's apples", 226: "Whispy's healing apples" },
  19: { 160: 'brick block volumes (grinishie1.c): not drawn, the bricks are collision' },
  20: { 233: 'Birdo', 236: "Birdo's eggs" },
  22: { 234: 'Arwing laser (drawn as a laser)' },
  25: { 160: 'breakable ice block volumes (gricemt.c): not drawn, the blocks are collision' },
  27: { 230: 'falling tools' },
}
// The kind-160 hazards that are drawn: stage -> item state -> [name, hit
// sphere radius, its offset y], from that stage DAT's ALDYakuAll[state]
// script (vanilla ISO: GrOt, GrMc, GrGd, GrCs).
const HAZARDS = {
  4: { 3: ['Banzai Bill', 9, 0], 4: ["Banzai Bill's blast", 36, 0] },
  9: { 2: ['car', 9, 4], 3: ['car', 9, 4], 4: ['car', 9, 4], 5: ['car', 9, 6] },
  10: { 2: ['F-Zero car', 8, 0] },
  12: { 2: ['Klaptrap', 8, 0] },
}

// HIDDEN, a look [name, scale, up, down, front, back, fill, shape, alpha], or
// null for kinds this table does not know (custom m-ex content). The kind
// alone decides, except for kind 160 (see STAGE_ITEMS): its stage and item
// state say whether a hazard the game shows is out.
export function itemLook(kind, stage, state) {
  if (kind === 160) {
    const h = HAZARDS[stage]?.[state]
    return h ? [h[0], 1, h[1] + h[2], h[1] - h[2], h[1], h[1], '#ff9a3d', 'ellipse', 0.45] : HIDDEN
  }
  if (HELD.has(kind)) return HIDDEN
  return ITEMS[kind] || null
}
