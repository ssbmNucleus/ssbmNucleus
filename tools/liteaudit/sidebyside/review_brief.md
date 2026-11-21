# Watch Lite vs Melee: side-by-side review

You are reviewing {count} pictures in `{pairs_dir}`. You did not build any of
this; judge only what you see.

Watch Lite is the app's flat 2D replay viewer. Each PNG shows one replay frame
twice:

- left, orange heading: what Melee drew, captured in Slippi's playback Dolphin
  and checked to be exactly that replay frame;
- right, blue heading: Watch Lite's drawing of the same frame, with its camera
  matched to the game's.

Some pairs add a close-up row: the same boxed area on both sides, enlarged.
Open every PNG at its native resolution. Do not judge from thumbnails or a
contact sheet.

## The question for each pair

Does Watch Lite show what the game shows, as a flat 2D drawing would? Look at:

- **Stage.** Every platform and the ground's body are present, the right shape
  and in the right place. Nothing extra: no slab below the real underside, no
  line the game does not show. Moving parts (Fountain of Dreams platforms,
  Stadium forms, cars, Arwings, Shy Guys, Randall) are where the game has them.
- **Fighters.** Present, in the right place, facing the right way, roughly the
  right pose and size.
- **Items and projectiles.** Present, roughly the right shape, size,
  orientation and colour family. A laser is a streak along its path, not a dot.
- **Effects Watch Lite draws** (shine, shields, Fire Fox / Fire Bird flame,
  Falcon Punch, Yoshi's egg, the sword trails of Marth, Roy, Link and Young
  Link): present when the game shows them, with the right shape, orientation,
  place and size. A sword trail is the swoosh behind a swing: judge its sweep
  (where it starts and ends along the swing), which side of the fighter it is
  on, how much of the blade it covers, its colours and its fade.
- **Movement dust** (dash puffs, run turns and brakes, jumps and double jumps,
  landings, aerial and wavedash landing clouds, run steps, roll and ledge
  dust): present when the game shows it, in the right place (at the feet,
  which side of the fighter), roughly the right size, shape, colour (white to
  grey) and how far along its fade it is.

## Out of scope: do not report these

- Watch Lite's flat style: flat colours, no shading, textures, lighting,
  backgrounds, HUD or outlines.
- Perspective. The game camera is 3D and Watch Lite is flat, so background
  parts shift and sizes differ slightly with depth.
- Capes, hair, tails and dresses.
- Thrown-victim poses: the exact pose of a grabbed or thrown fighter. Whether
  the victim is drawn, and where, is still in scope.
- Small effects: sparks, hit flashes, small particles, and trails other than
  a sword's swing (movement dust is in scope, above).
- Fighter draw order: which fighter is drawn on top.
- Custom m-ex characters and stages, which Watch Lite does not support.

If a pair's header says **FRAME CHECK FAILED**, the two sides may not show the
same moment: mark it UNCLEAR and do not judge it.

## Verdicts

Give one line per pair:

```
NN-id | OK
NN-id | WRONG | what is wrong, where, and on which side
NN-id | UNCLEAR | why (frame check failed, subject off camera, game frame unreadable)
```

Report only differences a player would notice at a glance. End with the WRONG
pairs again, the most visible first.

## Pairs

{pair_list}
