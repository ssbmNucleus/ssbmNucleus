# What a port has to handle

A list for whoever (or whatever) ports a fighter into Melee from another game. It is the things that were
found missing, one at a time, on the ports done so far (Shulk, Incineroar, Pokémon Trainer, Cloud, Byleth);
each line is here because leaving it out produced a fault someone saw in play.

It is not tied to one source game. For each item the work is the same three questions:

1. **Where does the source game keep this?** A fact about a move lives in one of five places: the
   animation clip, the move's script, a table of numbers (per fighter or shared by all fighters), the
   game's compiled code, or nowhere but published frame data and wiki descriptions. Scripts and clips are
   the easy two. The faults come from the other three.
2. **What does Melee have that does the same thing?** A script command, a fighter attribute, a donor
   state's own logic, or nothing (then it is C in the port's code file, or it is named as a difference).
3. **How is it checked in the game?** Not "the number was written" but "the fighter was seen doing it".

A port is not done while an item is unanswered. An item that cannot be done is said so by name, with why.

Nothing is invented where the source game is silent. A value taken from published data or guessed from
an unnamed number is marked as that where it is written.

## 1. The body

- Model, skeleton and scale. Size is the source fighter's own proportions against the donor's height.
- Every costume, with team colours. Never tinted recolours of one costume.
- A ripped body may be any one of the costumes. Find which by looking at its pictures, and make the others
  from it: the first costume in the port is the game's first, not the ripper's.
- Eyes, blinks, face swaps, anything the model shows or hides by state.
- The weapon: where it hangs, which hand, and whether a move holds it in the other hand.
- Other weapons that appear per move (a lance, an axe, a bow): which moves, which hand, shown and hidden
  on which frames. A weapon that is the fighter's own in another form sits in the same hand.
- A weapon that leaves the hand (thrown up, caught again): the fighter's own bone for it should follow it in
  the clip, because hitboxes ride that bone. The weapon's model may have a clip of its own as well: check
  the two agree before trusting either.
- Weapons that bend (a whip, a chain): their own joints and clips, and whether they fit in the joint limit.
- The joint a held victim hangs from during grabs and throws.
- Cloth and hair the source game simulates: on the donor's skeleton only the donor's own swinging parts
  exist, so say what is left stiff; on the fighter's own skeleton they are carried (section 11).
- What is drawn at rest is not in the model. A clip's visibility animation shows and hides parts a frame at a
  time, and the fighter's table of switches shows one group of each. A rip carries every state at once (five
  faces, one over the other): take out what rest hides before importing, and keep the one copy of what two
  states share.
- An eye may be several pictures over each other (a white, an iris, a highlight), each wrapped its own way.
  Name them for the importer in its own words, draw the wrapped ones out, and give the blink its lids from the
  game's own blinking face. An eye that looks about does it by a material animation (one picture slid over
  another: the model's own `model.nuanmb`, and tracks in clips). Say whether that is carried; where the iris is
  laid over the white once, it is a stand-in to name: the eye looks where it rests.

- What the body costs the engine each frame, by the game's own frame clock beside one other fighter. A body
  imported with the weightings it came with costs two to five times what the game's own do, and two of them
  drop frames. After the import and the recolours every costume is made lighter: a vertex's three heaviest
  joints in tenths, each weighting named by as few polygon groups as can be, pieces that shared their lists
  still sharing them, and whatever the importer left in the file that no joint names any more taken out. A
  blended vertex that comes down to one joint must stay a blend (the engine reads a one-joint vertex in that
  joint's own space: written as one joint it flies off as a spike). Look at the fighter again afterwards,
  beside a picture from before: this is how the spikes were caught.
- A weapon in the hand may be a second model (an article with a skeleton and clips of its own, made by the
  game's code as the move starts: the script says no more than `articles`), while the body's own model carries
  the same weapon where it rests (a gun in its holster on the leg). Neither is in a clip or a script the reader
  carries. List the body's parts no clip names, and for each say what the game does with it. An article that is
  the weapon in the hand is carried as a switched part of the body on the hold joint (the article's own `Have`
  joint laid on the body's), or the move is said to be bare-handed; say what of the article is not carried (its
  own clips, its other costumes).
- A clip's visibility track is not the last word: the game's code can hide a part every clip shows (the
  holstered gun, drawn throughout by the clips, hidden while the gun is in the hand). Check each weapon the
  fighter draws against what is at its resting place while it is drawn.
- An eye white's coordinates may lie whole repeats off its picture (Squirtle's: -1.85 to -1.15 down), which a
  picture that repeats draws as if on it. Laying the iris over the white goes by the picture's own place, so the
  white is moved onto it first, or the iris is laid nowhere and the fighter has blank eyes (Squirtle had them in
  every costume and on his roster tile). Look at each costume's face, eyes open, in the game's pictures.

## 2. Every action's clip

- Every action the engine can enter needs a clip: standing, walking, running, turning, crouching, jumps,
  falls, landings, shield, dodges, rolls, every flinch, tumbles, lying down, getting up, techs, ledge
  actions, item actions, being grabbed and thrown, entry, taunts, results.
- **How long each lasts is not the clip's length.** The source game says when the fighter may act
  (a cancel or free frame). Find where: per move in the script or motion table, per fighter in a table of
  common actions (dodges, rolls), or one shared table (shield drop). Actions that run the game's *shared*
  scripts are the ones that get missed, because the fighter's own files say nothing about them.
- Which actions end at their free frame, and which play on if nothing is pressed (attacks, taunts).
- Which actions the engine ends by its own numbers, so the clip must *not* be cut (landings, flinches).
- Speed changes inside a move (the source script slowing or speeding its clip).
  A clip is as long as the game plays it: where a script changes the speed and never says when the fighter may
  act, the clip runs on to its own end at the last speed set (cut at the speed change, a reflector's opening
  went in 4 frames long for the game's 10 and a side special's start 7 for 19, and nothing said so until hits
  "past the clip" were dropped). Count the installed frames of every special's clips against the game's clip
  lengths before building any state on them.
- Who moves the fighter: the clip's root, the state's own physics, or the port's code. A clip whose root
  travels in a state that only applies friction goes nowhere.
- Clips that are several source clips joined, or one source clip cut over several donor actions.
- Facing: every clip looked at facing left as well as right. A clip mirrors by itself, so this comes to a list
  and a few pictures: the clips the game keeps a second copy of for the other facing (in Ultimate a name that is
  another's with `l` on the end: a reflector's start and end, so that he faces the screen), each carried or
  named as a stand-in (without it he shows his back facing left); and a picture each way of the specials, where
  code places things. `verify` makes the list. Pictures of every normal both ways found nothing it did not.
- **How many frames the engine shows of a clip.** Melee enters most actions one frame in (it steps the
  animation as it changes state, or starts the clip at frame 1): a clip stored as F frames is F - 1 frames of
  action, and a port's clip goes in one frame longer. Others are entered at frame 0 and play whole (a grab, a
  shield drop, getups, techs, landings, a taunt, the second and third jab). Read which from the engine's code,
  state by state, and count the donor's own in the game. The port's own states are entered by its own code:
  know what that does.
- Clips the reader refuses (tracks with override flags: Incineroar's 44, every being-thrown clip `e01thrown*` among
  them) are listed by the action they were for, with what the engine shows there instead. Being thrown happens in
  every match: it is not a corner to leave. So are clips the source's own decompressor refuses: find exactly what
  they have that the others do not (codec, its settings, track format) and decode them before letting a pose stand
  (Rivals 2: 38 of Zetterburn's 200 are ACL-compressed, which CUE4Parse decodes only through a native library it
  does not ship; `echo_rivals2/acl.py` reads them from their own bytes).
- Every common action in `report.json` `held` (a standing pose held, "no job for this action") is looked up in the
  engine and the source before it is let stand: a name the source spells differently gets its pair in
  `own_route.MELEE_NAMES`, a state the engine never enters (ItemBlind) stays held and is said so. Until 2026-11-13
  every own-skeleton port froze in its jump with the Screw Attack, a common item, and opening a Parasol: the game
  names them `itemscrew` and `itemassist`, and only an old campaign's table paired them. An action the engine
  picks by which clip a fighter HAS (DownSpotU, else DownSpotD, `ftCo_DownSpot_Enter`) follows the donor's
  choice, not the source's: give the donor's one a clip that leads into the state the engine goes to next.
- A source that plays its rolls, getup and tech rolls and ledge climbs IN PLACE (its code moves the fighter:
  Rivals 2) gives Melee's states for them, which follow the clip's root, nothing to go by: the reader gives those
  clips root travel from the game's own speeds (`echo_rivals2/transcode.py:give_travel`). The driver's `travel:`
  line keeping 0 clips and verify 11.9 at 0 are the sign; a round's roll that `went +0.0` is the proof.

## 3. Every action's frames

- Frames nothing can touch the fighter on: dodges, rolls, techs, getups, ledge climbs and rolls, ledge
  and floor attacks, the start of some specials. Written from the source game, replacing the donor's.
- Armour: which frames, and whether it gives way above some damage.
- Landing lag per aerial, and the window in which landing cancels it.
- Smash charge window. Jab chain windows. Any "press again" window.
- Check the engine's frame convention against the donor's own known moves before trusting an offset
  (in Melee a hitbox written on frame N hits on frame N; a grab box written on N grabs on N+1).
- Code of the port's own that runs once a frame runs *before* that frame's clip moves on: the frame it reads
  is one less than the frame a hit will find. (Armour written from the script's frames was a frame late
  until a jab was landed on each frame in turn.)
- A script's loops (a count, then what to repeat) are written out before frames are counted; a loop with no
  count goes round with its clip.
- Each timed clip's keys reach the frame before the fighter may act: a script that changes its speed again after
  that frame has its keys stop at the change before it, and the clip goes on at the speed in force
  (`oneshot.to_cancel`; Incineroar's side special was cut to 41 frames of 58). Code of the port's own counts a
  clip's frames by the clip's time keys in the spec, never by the script's rates again (a rate is frames of play to
  one of the clip: 0.9 plays it faster).
- A choice with two sides is written as its plain side (a tapped special, the stick held no way), the side asked
  first kept apart (`alternatives`); a wait that ends in such a choice ends there, whichever way it goes. Slap
  City's squat asks on its frame 5 whether jump is held (a full jump, else a short one): looked for as one plain
  go-to, no end was found and Ittle Dew kept the donor's squat of 4 for the game's 5.
- A game whose dodges, rolls and techs are engine code (Rivals 2: clips and speeds, no frames in any file) keeps
  the donor's untouchable frames: answer 3.1 as a difference and say so; it is not a fault the port can fix.

## 4. Hits

- Per hitbox: frames, the bone it rides, place, size, damage, angle, growth, base, fixed knockback,
  element, what it does to shields, whether it can clash, its sound (how hard, what kind).
- Who it can strike: grounded only, airborne only, the held victim only, anyone but the thrown victim.
- Hitboxes drawn out along a line (a blade's edge): Melee has balls only and four of them. Cover the far
  end exactly; join rows of like balls before dropping any.
- The order hitboxes are tried in (sweet spot against sour spot).
- Hits that strike again every few frames; hits that link into the next; a late weak hit that must not
  strike what the early hit struck.
- Angles the engine does not have (a hit that carries the target along): what is written instead.
- Hitboxes whose numbers are set while the game runs (by the target's damage, by distance, by charge).
- Grabs: boxes, frames, separate boxes for grounded and airborne targets, reach. Pummel. Each throw's
  release frame, damage, angle, knockback, the hits it makes on bystanders, and which way it turns.
- A hitbox the script makes and never ends is one the game's code turns on (a shot fired by something else:
  an aiming reticle's three shots in a smash). Its frames are not in the script: take them from published
  frame data, mark them as that, and hold them against what the game's own files do say (the shot's sound
  plays on the frame it hits).
- More than four hitboxes out at once in the source (Ivysaur's down smash: five): Melee holds four, the driver
  keeps the strongest four and notes it; `verify` says the damage that went (4.1), it is not a fault. Look
  whether the one dropped was a sour spot the move needs.
- A throw is written with the game's own damage, 0 included: a throw of 0% leaves its damage to a hit for the held
  fighter alone (Incineroar's back throw: 0% at 47, and 14% from a `catch_only` box), and 1% would add a point.
- A box the source strikes again while it stays out (Slap City's SARA), or gives another attack property (SASATP),
  goes on from that frame as a box of its own. Read as one box all the way, Ittle Dew's forward air struck once
  for the game's three, with the first property throughout. Count the hits on a target held where it stands (`pin`).

## 5. The fighter's numbers

- Walk, dash and run speeds, traction, air speed and acceleration, gravity, fall speeds, weight.
- Jumps as *heights*, turned into the engine's starting speeds; double jump; short hop.
- Units and formulas differ between games: compare a measured height or distance, not a copied number.
- Say which numbers stay the donor's and why.
- Go down the target engine's whole block of fighter numbers, one by one, and for each say: the fighter's
  own, set by the route, or the donor's and why. The first ports set twenty-one and nobody looked at the
  rest: traction, the walk's start, what slows a fighter in the air, the shield's size, the air jump's
  sideways share, how hard it throws an item were all the donor's.
- Which of the source's numbers is which of the target's is settled by the fighters that are in BOTH games,
  all of them side by side: a pair that is the same number shows the same ratio for every fighter (the walk's
  two starting numbers are Melee's two times 1.05, each with each; the number of jumps is the same). A pair
  whose ratio wanders was retuned fighter by fighter; if the engines use it the same way, the source's
  number still goes in as it is.
- A thing that is two numbers in both engines goes in as two (steering in the air: what the stick is
  multiplied by, and a flat part). A sum written into one of them leaves the donor's other half in.
- A number the engine multiplies by the model's scale itself (the shield's size) is divided by the scale
  the fighter data draws the model at.
- Some of a fighter's facts are in the roster's entry, not in the fighter data: whether it jumps off walls,
  which costume a team wears.
- What a source number does is read in the source's own code that moves the fighter, not from its name. Slap
  City's `airbrake` is never read for a fighter (it brakes the game's articles) and `airdecay` slows one not
  steering; its steering is one step toward air speed x stick, the same however far the stick leans: all of it
  Melee's flat part (+0x68), none the stick's (+0x64). Ittle Dew's first port slowed three times too fast and
  steered with the donor's flat part on top. Read the numbers back in the game (`attrs`, `vel`).

## 6. Each special, and anything else with behaviour in code

Read three things for every special: its scripts, the fighter's own parameter table for it, and a
written description of the move (a wiki's is fine). The description is the checklist; the first two say
how much of it the files will give you. Unnamed numbers in a table can often be named by hashing likely
words, or recognised by value against published data.

- What happens to the fighter's speed as it starts, on the ground and in the air.
- Turning round: as it starts, during a charge, once before a swing. On which frames.
- Charging: how long, what full charge changes, whether it releases by itself.
  How long one level lasts, how many there are, what each adds. A full charge may be a script of its own
  (other hitboxes, other knockback, no armour, damage to the fighter): two scripts under one name, and the
  target engine needs somewhere to put the second.
- Ways out: which buttons end it early (shield, jump, dodge, the special button again, the stick),
  between which frames, and what plays when it does.
- Held or toggled: does it go on when the button is let go?
- Projectiles: speed, life, damage, whether it passes through, holds what it hits, what it does to a
  shield, how it looks (a model, or particles that need a stand-in), ground and air versions.
- Recoveries: speed upward at the start, catching ledges at a distance, catching walls, how many times,
  what happens on a miss, whether the fighter is left helpless.
  In the air before the rise: does the fighter hang or fall? A rise that is in the clip is followed from the
  first frame in the source game. The donor may also multiply the clip's travel in the air by a number of
  its own.
  The landing after a helpless fall: the special's own table if it names one (`fire_landing_frame`), else the
  frame the game's motion list frees the fighter on in its helpless landing (`landingfallspecial`), less one
  (30 there is the published 29). Count the landing's frames in the game.
- A dash across the stage: its speed, what a charge adds, what stops it (an edge, a fighter in the way), and
  who brakes it when it ends. Left to ordinary friction it goes twice as far as the source's.
- A move that grabs or latches: the pull, the follow-up hit, what picks between its versions.
- Counters, reflectors, absorbers.
  For a counter: the frames it catches a hit on, what it gives back (a multiple, and a least), whether the
  fighter can be hurt around the window. The target engine's counter may be built another way (a bubble
  like a shield, the multiple in the donor's data, applied for one fighter only): read the donor's code.
- Meters and gauges: every way it fills, every way it drains, how long it lasts, what it changes
  (which numbers, which moves get a second version), where it is drawn.
- Second versions of moves and what picks them.
- A chain that goes on only if the first swing hit.
- Landing in the middle of an air special, and the reverse.
- Two scripts under one move's name. A weapon of the fighter's (a reticle, a can, a whip) registers scripts
  under the fighter's own move names, before the fighter's or after, and nothing in the file says whose each
  is. Keep the fighter's own for the move (its scripts are the longest run of registrations with no name
  twice) and the weapon's for the weapon. Taking the wrong one writes a smash with no hitbox.

- **Things a special makes** (a can, a clay, a figure that shoots: an item of the port's own):
  - It never outlives its use: removed when its own life runs out, when it leaves the stage's bounds, and
    when its fighter dies.
  - It does nothing until it is given a state after it is made.
  - The box the stage stops it with is the second one in its common numbers (up, down, ahead, behind); one
    under 3 tall or wide falls through things and is made 3.
  - A hitbox copied from a template item keeps the template's "hit again after N frames": set it from the
    source.
  - An item's code and the fighter's are separate files that cannot call each other: they talk through the
    item's variables.
  - An item plays one of the fighter's own sounds by the bank's own number for it (5000 plus its place).
  - A shape the engine has no form for (a slab of thousands of triangles for a pixel figure) is a flat
    cut-out of the source's own picture, said to be one.
- The frame a state of the port's own is entered on already runs that state's movement: count it as the
  state's first.
- Probe tests in one boot share one match: an item left out by one test is still there in the next. Damage
  goes stale across them too (the third dash attack of a run did 9.1 for 11): a test that reads damage has a
  match of its own.
- An item that breaks or goes off is hidden by setting the hidden flag on its whole model; the kit's own
  "set hidden" call SHOWS a model. Look at a picture of the frame after it breaks, in the open, not against a
  target.
- An item made from another fighter's item keeps that item's removal effects and removal sound unless they
  are set to none: a white puff wherever one is removed. Look at the frame an item is removed on.
- A sound that code plays by its place in the bank is only right on a bank built after the driver's last
  run: the bank is rebuilt with every build, and each such sound is checked by recording on that build.
- A sound that only code or an item plays (no move script names it) needs a plain place in the bank: on a
  place whose donor script loops or bends, it cannot be called. List such sounds from the game's state code,
  not only from its move scripts.
- Two samples can be one sound (one the tail of the other). Before saying a sound is heard, match the samples
  against each other, and report every match of a short sample, not only the best.
- A thing shown for a few frames (an aiming mark, a flash) is checked with a picture on every stepped frame;
  pictures taken in real time miss it.
- Where an engine action may end a move (an aerial out of an up special), step it and read the states: one
  frame of an ordinary state in between is a way out. Wrap the engine state's own callback.
- A hit that one object asks another to make (item to fighter to item) lands a frame or two after the ask.
  Count the frame it lands on with a target at the muzzle, against the published frame.
- Things that come in a random order (five gunmen) are counted in one frozen run of the whole round and told
  apart by what they do.

- List every sound the game's state code and its articles' scripts play, not only what the move scripts
  play. Each one the port's code plays is declared by the fighter's module, so that the bank gives it a place
  code can call.
- A sound the game ends early (with a state, a landing, a hop) is checked by matching the beginning of its
  sample and by where its loudness falls: a whole-sample match of a cut sound fails though it is heard.
- Before calling a sound a stand-in for "one every fighter shares", look for the fighter's own in the
  article's state code (the can's explosion was his own).
- A sound of a state ends with the state only if it is played the way the engine plays such sounds; an
  item's sound that must be ended is played and ended with the item's own pair of calls.
- Two of a fighter's own items must not meet as hits unless that is meant: decide from the game what one does
  to the other, and have the fighter's frame code see it a frame ahead.
- A mark one stage puts among the game's moves for another stage to read must not reuse a mark a third tool
  reads for something else.
- A state of the port's own in which the fighter himself strikes (a stab of a blade, a kick as a dash ends, a
  flight that hits) gets its hitboxes from the game's script for its clip, as an attack does: the fighter's
  module names those actions (`HIT_ACTIONS`). The own-skeleton route writes none otherwise: it empties every
  special's script, which fits only a fighter whose specials strike with the things they make.
- Naming a parameter table's values (the file holds hashes). A hash holds the name's LENGTH, so word
  combinations are tried by length first. Start from the table names (`param_special_n` ...), then the game's
  own nickname for each move as a prefix, `<nickname>_<what>` (Wolf's side special is `illusion`, his up special
  `fire`: `fire_rush_speed`, `illusion_end_air_brake_x`, `reflector_air_start_x_mul`, `blaster_shoot_speed`).
  The names found go in the fighter's module (`NAMES`). Say how many are still unnamed and which values they
  hold (Wolf: 83 of 120 named in three passes).
- A state of the port's own has four calls (animation, interrupt, physics, collision), and what none of them
  does is not done. A physics call that does nothing on the ground leaves the fighter where he is: a state that
  moves him along the ground hands on its ground speed each frame itself (`Fighter_PhysGround_ApplyVelocity`: a
  flight along the ground went 2.4 units until it did). In the air the engine moves him by his own speed
  (`self_vel`); gravity and drift are calls the state makes.
- A state is entered so that its script runs (`ActionStateChange`, then `Fighter_AdvanceScript`), and its ground
  and air forms hand over on the frame the clip is at (`ActionStateChange(frame, ..., 0x5000, 0)`). The
  collision call says what the stage may do to him: stay on the ground past an edge or fall off it
  (`Fighter_CollGround_PassLedge`, `Fighter_CollGround_StopLedge_EnterFall`), pass a ledge in the air or catch
  it (`Fighter_CollAir_IgnoreLedge`, `Fighter_CollAir_GrabFacingLedgeWalljump` for a recovery).
- The engine's own calls for what a special ends in or puts up: the helpless fall and its landing
  (`Fighter_EnterSpecialFall`, `Fighter_EnterSpecialLanding`); a reflect bubble (`Fighter_CreateReflect`), which
  any change of state takes down, so it is put up again on each frame it should stand; the joint that pitches
  the whole body (`__engine_XRot`, joint 2 of every rig this route makes).
- The clips of a port's own states go on donor actions left free (the module's `CLIPS`: clip to donor action).
  The driver's own rows still put the specials' clips on the donor's special actions as well: know which action
  each state plays. `own_duckhunt.py` and `own_wolf.py` are the worked examples (kept under the git tag
  `archive/fighterport-character-specific-2026-11`, as is every `own_<fighter>.py` named below); a special like neither starts
  from the same four calls.
- The published pages a special is held against (frame data, a wiki's description) are saved in the work folder
  as they are read (`<work>/published/`, with the date). A port made without them says which numbers it could
  hold against nothing.
- The engine's source is the Melee decompilation: every `file.c:line` in this list and in the code is in it, and
  its `config/GALE01/symbols.txt` names every address (a stack of bare addresses from a probe is read with it).
  Where it is checked out is not written in this repository: ask, or look where the app's own harness looks
  (`MELEE_DECOMP`, default `~/projects/melee`).
- A thing a special makes whose model holds its figure in poses, a mesh each (`<Name>_A`, `<Name>_B` ...), that the
  game's code shows one at a time, carries a picture of each pose it shows in the port and switches them on the
  frames the article's state code does (read there: its motions may have no clips). The gunmen stood facing the
  camera through their shots until they did. A pose left out (one only being struck shows) is named.
  (`own_items.pose_meshes`, `own_items.cutouts`, `own_items.SHOW_POSE`; SPECIALS.md, a thing a special makes.)
- An effect a special's CODE makes is made on the frame that code makes it, not on the frame it should show: its
  pieces wait frames of their own after it is made. A gunman's muzzle flash is made 5 frames before his shot and
  its pieces wait 5 to 7; made on the shot's frame it came after the bullet. A sound the code plays with it goes
  on the same frame. (SPECIALS.md, a helper that appears and acts.)
- A thing that strikes many times in a row holds its target only if it keeps up with the push of its own hit:
  step the round of hits in a test and read the target's damage after each. (Greninja's full Water Shuriken
  stopped where it first struck and landed one of its five hits.)
- A counter catches with Melee's ball round one joint (`ftColl_8007B1B8`), not the newer game's whole body: ride
  a middle joint and size the ball to hold the whole body, and check it with a high hit and a low one (Greninja's
  on joint 0 at the game's own size held his legs only; a jab to the chest struck through it). (SPECIALS.md, a
  counter.)
- A move that puts the fighter somewhere by hand (a counter's strike behind the one who struck, a warp) tells the
  collision where he now is, as Melee's own Warp Star and Barrel do (`mpColl_80043680`: its three places set to his,
  its flag 0x20; `test_port_rules`): else the next collision sweeps from where he stood and lands him partway
  (Greninja's Substitute: 8 short, on the near side). Look at where he comes out against where the source game puts him.
- A script with more than one hitbox of the same id over the same frames holds alternatives the game's code
  chooses between (one strike for each way the stick is held). The driver keeps the last and says so in its notes
  ("alternatives"); the module carries the others and puts the chosen one on. (SPECIALS.md.)
- A move that hides him or makes him unhurt is undone wherever he leaves it, not only where it ends: the frame
  code undoes it when he is found in a state that is not his own (a hit, a ledge, the blast zone). Test the move
  struck, or let it end at a ledge, and see him again. (SPECIALS.md, a move that vanishes.)
- A flat picture taken from the source game's particle effect is looked at in the game before it is kept: it can
  be a plain mask the game colours (Greninja's water was a white square). Else a blob in the effect's colour,
  named as a stand-in.
- Every value of the fighter's parameter file a special reads is read by its name, found with
  `python -m fighter_port.prc_names <fighter> <words>` (the file holds only hashes); a value not found is named as
  READING with what it was taken to be, never read by its place in the table.
- Every clip a state of his own plays is named in the module's `CLIPS`, the ones the driver already put on an
  action included: an action not named has its script emptied and its sounds go silent (verify 7.1).
- A thing a special makes may keep its numbers in its own state code, not in the parameter file, and some in
  neither (set by the game's own program, which is not in the dump): read its own states first (its life, its
  counts), and take an unnamed parameter value for it only when no code reads that value and its name's length
  runs with its neighbours' (one a helper, as their other values do); never because it looks the right size.
  Then step its flight in a test (`PROBE_ITEMS=1`) and read how fast and how far it goes. (Duck Hunt's bullet:
  life 10 in its own code, speeds 8, 9, 8, 5, 8 by the gunman; the 4 and 12 once read as its speed and life were
  a gunman's seconds lying struck and his frames turned to aim.)
- A command grab (a special that takes hold): the engine's grab (`Fighter_InitGrab`, 0x8007E2D0) with the common
  grabber callback, a grab box made from code a frame before the game's grabbing frame, and the engine's own Catch
  states and throws after it (`own_gaogaen.py:Grab_Box`, `S_Caught`, `Whip_Frame`). Say what the source does after
  the catch (ropes, a return, a second hit) and what stands in; Melee has no grab in the air.
- A counter that keeps power for the next hit (Incineroar's Revenge): a value per player, laid on each hitbox made
  while it lasts by a wrap of `cb.Phys` (after the script makes the box, before collision: `own_gaogaen.py:Rev_Phys`),
  spent on the first victim, ended by time in the frame code. Test it struck, then with the next hit, then after the
  time.
- Some moves are registered only as SHARED scripts (`animcmd_game_share`: Shulk's five Monado Arts, and the plain
  `game_specialn`). The reader takes a shared script for a name the fighter has no script of its own for
  (`moves.game_scripts`); a special whose `game_` script is missing from `game.json` while its `sound_` and
  `effect_` scripts exist is this case.
- A special that is a MODE (it changes the fighter's numbers for a time: Shulk's Monado Arts) follows SPECIALS.md
  "A mode that changes his numbers": movement in `fd->attr` kept and put back, damage taken through the engine's
  own multiplier, his hits from each hitbox's own numbers as it comes out, ended at a KO. Its numbers are read by
  name from the parameter file, and at least two are seen changed in the game (`attrs`, and one hit in the mode
  against the same hit without).
- Ultimate's words for a fighter's values are not the move's: try `blow` (knockback dealt), `damage_mul` (damage
  TAKEN; dealt is `attack_power_mul`), `spd`, `height`, `brake`, `active_time` and `unavailable_time` (seconds),
  `air_speed_x`/`air_speed_y` with the move's words; a name of four or more words is believed only when its
  pattern repeats across the table.
- The driver log's `travel` lines name what becomes of each clip's root travel. A clip of a state of the port's own
  that is `dropped` no longer moves him: the module gives the speed (the clip's root span over the frames the disc
  plays it, `own_shulk.py:LwHit_Phys`); one that is `state` moves him on the ground only through
  `Fighter_PhysGround_ApplyFriction` (it reads the engine's travel), never through gravity alone in the air.
- A mode is shown as the game shows it, by its own effects from the fighter's effect file (SPECIALS.md "A mode
  that changes his numbers"): the symbol where it starts, the sign, the aura on the joints the mode's script names,
  a held effect given a life and given again while the mode lasts (`Plan.use(lasting=, only=)`). Never a tint of the
  whole body (Shulk's arts were a body tint until 2026-11-13). What the game recolours through its effects' own
  colours (the Monado's blade) gets a stand-in in the mode's colour at that part, named. Look at it as it starts
  and while it is on (`sk_arts_show`).
- A mode's damage and knockback reach the throws: a throw's hit is not a hitbox of the script but the fighter's two
  throw hits (`fd->throw_hitbox`, set by the throw command and read on the release), laid on from their own numbers
  (`own_shulk.py:Arts_Throw`). Shulk's throws were his plain ones in every art. Test a throw in two modes and read
  the damage.
- Knockback TAKEN in a mode (`<mode>_blown_mul`) is the engine's worked-out knockback times the mode's number in
  `fd->cb.OnTakeDamage2` (`own_shulk.py:Arts_Blown`): the engine calls it after it works the knockback out and
  before it is used, and every change of state clears it, so it is set each frame the mode is on.
- Where the move's words do not find a value, try the fighter's own vocabulary (its motion names' and its code's
  status names' words, `blown_mul` for knockback taken) and weigh each find by `prc_names.chance`: a name of three
  words after a prefix, out of a thousand, finds something by chance (Shulk: `jump_sqrt_yield_string`); one of two
  does not (0.001). List what was tried for a value that stays 1.
- The specials are the moves the source's own input table starts (Slap City's `standardSCinputTrigger`), not the
  moves named like them: a moveset keeps leftovers nothing starts. Ittle Dew's tapped `nspecial_v1` was ported as
  her neutral while the game's is `nspecial`, which charges.
- A charge may let go into a part-move its own check starts (Slap City's SAPM on the charge's frame: the button
  up, or the count at its most). Count as the check does (the game adds the frame, then asks: 1 on the frame the
  swing stops) and read a full charge's swing frame in the game a frame at a time. Counted from the next frame,
  Ittle Dew's swung a frame early.
- Where a thing a special makes goes can be terms of the stick (Slap City's spawn speeds: a base, and the stick
  times a number each way): read each term and test the special with the stick held each way it reads (the bomb
  thrown by the stick, the teleport's ball steered by it).
- A thing a special makes takes the source's own model where the source has one (the reader writes the article's
  mesh: Ittle Dew's bomb, 618 triangles); a picture is made only where the source draws particles, and named.
- A move that sets its own gravity before a jump height (Slap City's teleport: gravity 10, then jumpheight 3)
  rises under its own gravity: the height is turned into a speed with the move's gravity, not the fighter's
  (SPECIALS.md "A move's own gravity").
- A thing that strikes the same target again every few frames keeps that beat (Slap City's `refreshAtkFrames`:
  the held fireball strikes every frame, six times); dropped, it strikes once.
- **A status a hit leaves on the TARGET** (a burn, a mark: Rivals 2's Zetterburn) is kept by the attacker's
  per-frame code over every other fighter (`Fighter_GetGObj`): a hit of his is the target's percent rising with
  `dmg.source_ply` his, its element in `dmg.hit_log.attribute` (the reader gives a burning hit Melee's fire);
  damage laid on with `Fighter_GiveDamage` every so many frames, shown with `Fighter_ColAnim_Apply` (fire's colour
  is 11), the status ended by a KO and its own ticks never taken for hits (`own_zetterburn.py:Burn_Frame`). A
  move that USES the status (Zetterburn's strongs and forward throw consume the burn) is read in the same code.
  Look in a stepped test: the bag's percent rising every tick and stopping after the last (`zt_fireball`). Its
  numbers are the game's, or a stand-in said as one. Its own sounds (set alight, consumed, ended) are the source's,
  played from the attacker's code as the source's code plays them: `CODE_SOUNDS`, then
  `Fighter_PlaySFX(fd, 5000 + place, 127, 64)` (ft_PlaySFX: not ended when his state changes;
  `own_zetterburn.py:Burn_Sound`), and named under their tests in `audio_check.ENGINE` (9.24).
- A move handed over from the ground to the air (or back) is handed over on a frame BEFORE the one its script
  makes its boxes on, never on that frame: the hand-over takes down the boxes made then, and the new state's script
  goes on after them, so they never come out (Fishbunjin's Bell Ringer struck nothing until handed over on frame 8,
  its boxes made on 9). Look in the game: the move strikes a target it overlaps. (SPECIALS.md, Traps.)

## 7. What it looks and sounds like

- Voice and move sounds on the frames the source plays them; nothing of the donor's left behind.
  Which sound a move plays is the script's word, not the sound's name (a game may only number them). A bank
  has so many places: fill them by what the fighter's moves play most, and list what found no place.
  Sounds the game's code picks (an attack grunt, a charge's hum) are in no script: say how each was taken.
  Sounds are two lists from the built files (`verify` makes both), each wanted empty or explained line by line:
  the sounds a script of the game's names that the port's bank cannot play, by script and frame; and the samples
  in the bank that nothing plays. A sound can be in the bank and still not be playable: on a place whose donor
  script loops or bends what it plays no script can call it, and the script line that plays it is dropped
  without a word (a gun going back to its holster on frame 40). A recording is for what a list cannot say: a
  special's sounds on their frames, and a sound cut short.
- Sword trails where the source draws them, in the source's colours, and *not* on moves the source marks
  another way (a thrust is not a swing).
- Effects the engine has its own of (dust, a charge gleam); effects that have no form here; a stand-in
  only where the move is unreadable without one (a beam of light), and said to be a stand-in.
- Anything on the HUD.
- Roster tile, portraits, stock icons, name, announcer call, results screen.
- The colour a move lays over the body (a flash as a counter starts, a pulse while a charge builds): the
  script gives the colours and the frames. Melee has an overlay for it, set from the port's code each frame;
  the donor's own colour animation for that action comes out.
  Read it back: the report's `flashes` and `own_flashes` name the actions that got one. Count the game's scripts
  that set a colour (in Ultimate `FLASH`, `FLASH_FRM`, `COL_NORMAL`; in Brawl the overlay events) and hold the
  two numbers together: a reader that leaves those commands among the effects answers this line with nothing,
  and no warning. A special's states are not in the driver's table: they get theirs through the fighter's
  module.
- Sounds every fighter shares (the swing of a punch, a kick, a sword) are in no fighter's bank. Play the
  target engine's own for the same thing, by the numbers its own fighters' scripts use. A jab that is a punch
  is silent otherwise.
- A bank can gain samples. The scripts that play them must be numbers the donor's bank already had (the
  installer points only those at the new bank): the big and the small form of each voice are never played in a
  new bank, and are the room.
- A fighter's own particle effects, by the names in its effect file. A stand-in comes from pictures of every
  shared effect the target engine has (photographed once, by number), and is put where the move's hitboxes are.
- Where the port carries an effect file of its own (section 11), the fighter's particles are converted, one
  emitter to one generator, and each is looked at in its move. A particle much longer than it is wide (a
  speed line along an attack) is not a square: draw its picture thin in the square and turn it on the screen
  to where it points, or it shows as a burst. What has no form in the target engine is listed, not faked; a 3D
  shape is flattened into a picture and named a stand-in (the last line of this section).
  After the driver, read the report's `effect_file.not_carried` set by set and mark each: decoration (listed),
  or something a player must see to play the move (a shot, a shield, a reflector, a charge). Those get a
  stand-in, said to be one, and the list of them is given with the port (Wolf: 9 of 29 sets carried; the laser
  became a flat picture in its own colour, the reflector a tint of his body while it is up).
- Voice lines may be named by who speaks (a dog's, a duck's), not by what they are for: match on the word
  for the occasion. A donor voice sample the fighter has no line for is made silent, and is never used as
  room for another sound: the engine and the donor's kept scripts play that sample on its own occasion (a
  jump, a ledge caught, a win), and whatever sits in it is heard there.
- A sound of the fighter's that the bank has no room for is replaced by the donor's only where it is the same
  thing (a sword's swing for a sword's swing). A sword's swing under a peck or a gunshot is the donor left
  behind: the move is quiet there, and the sound is listed.

- The source game gives sounds to clips that have no move script (a taunt, an entrance, a win pose, steps,
  landings). A reader that keeps only the scripts of moves that hit drops them all. The taunt at least gets its
  own, on its own frames; for the rest say which of the target engine's shared sounds stand in (steps, a
  landing) and which occasions are silent.
  The same goes for the fighter's own sounds in scripts the port does not write (an entrance, a dash's stop and
  turn, a roll and an air dodge, a crouch, a tech's voice line) and for the steps and landings inside the ones
  it does: none is in the bank, and a recording never looks for them. `verify` lists them by name; each is
  carried, or named with what is heard in its place.
- The target engine has one taunt and the source three: choose which it is for THIS fighter (the one it is
  known for), not whichever an earlier fighter's table left there.
- A donor voice slot that nothing plays any more (a special's line, a victory line, the taunt's, once those
  scripts are written anew) is room for the fighter's sounds. One the engine or a kept script still plays (a
  jump, a ledge caught, asleep) is never room: it holds the fighter's sound for that occasion, or silence.
- Every picture of the fighter's effect file is read before the driver's long steps
  (`effects.textures(effects.texture_archive(...))`). A picture in a format the reader does not know (Wolf's
  file had one of 49 at sixteen bits a pixel, a white disc) costs that effect, which is said; it does not stop
  the run after the clip bank is made.
- An effect the game's script makes follow a bone (EFFECT_FOLLOW...) is held by its joint and goes with the
  fighter, not given off once where the move began: Wolf's Fire Wolf burned where he took off while he flew
  away. A held effect takes the joint's place and the way he faces, not the joint's turn: where the fighter's
  code turns the joint (a flight aimed by the stick), the code plays the effect made for that turn. What the
  game draws on a 3D shape about the body (a sheath of fire) gets a stand-in that wraps the body, named in the
  list. `verify` reads every following call's generators in the built effect file.
- A donor sample whose own script loops or bends what it plays (Marth's charge sound, its pitch rising) is no place
  for a sound the port's scripts or code play as it is: none of them can call it there, and on a route where the
  donor's own scripts are gone nothing plays it at all. Wolf's Blaster sound sat there, silent, until the bank
  chooser was told so (`voice.choose`); `verify` 7.1 names any sound a written script plays that the bank cannot.
  A row that put such a sound there still owes it a plain place, and the bank is chosen so (Ivysaur's neutral
  start sound sat only on the donor's charge place, and his own neutral, written anew, was silent).
- An effect emitter that draws with more than one picture is not drawn by its first picture alone. Where the
  source cuts the first picture's see-through-ness with the others, the first alone can draw a dark square:
  Squirtle's Withdraw water wall (`waveline1`: a line picture whose inside is half see-through dark grey, a second
  water picture and a gradient) showed as a dark box around him. Its pictures are joined into the one Melee draws
  as the file's combiner says (`effects.combiner`, a reading: multiply, add, subtract; a grey picture with no
  see-through-ness of its own joins as a mask); where what they make still draws a square or a dark box
  (`effect_shapes.draws_square`), a picture made see-through where it is dark (and cut round, for a square) stands
  in, named. An emitter that only bends the picture behind it (a refraction) has nothing Melee can draw and is left
  out, named; one that bends its own pictures draws them without its map of offsets (an "indirect" picture, grey
  noise, was drawn as its first). The receipt's `effect_file.pictures` counts what each got; still look at the
  specials' pictures for squares.
- A sound a script names may be in the fighter's bank only as numbered variants (`se_gaogaen_special_h04_01`,
  `_02`: the game's code picks one). The first stands for it under the script's name (`voice.choose`), a stand-in
  for the pick; a name found in neither form is listed, never passed over.
- An effect emitter that draws its picture on a 3D shape (a ring, a blade, a dome of water) is a STAND-IN: the
  shape is read from the file (section G3PR), its pictures put on it, turned by the emitter's own start turn (and
  the script call's, for a shape laid in the effect's space), and flattened into one picture as the camera sees it
  from the side; flat particles carry it with the emitter's own timing, colour, alpha and size keys, as wide as the
  shape is drawn. One picture a shape, pictures and turn, shared by the emitters that draw the same, and no more
  pixels than it is drawn large (32 a side at most): it counts against the fighter's room (11.26). Where the
  texture bank would pass 256 KiB its largest pictures are halved, the flattened shapes first, and the receipt
  names them (`effect_file.fitted`). The shape does not turn in depth:
  its spin and random turn about any axis but the one toward the camera, a shape that grows more one way than
  another, and any movement of its picture over it are named per emitter (`effect_file.stand_ins`). A shape that
  shows nothing from the side, a refraction, and a shape the fighter's module stands in for by hand
  (`HAND_STAND_INS`) are refused, named. `verify` 7.10 counts the carried shapes apart from the refused ones; look
  at each in its move.
- No flattened shape is drawn wider than all the camera shows: one that would be more than 500 units across
  (`own_effects.WIDEST_STAND_IN`; Final Destination's blast zones are 492 apart) is refused, named with its width,
  and `verify` 7.10 counts it with the refused. Greninja's Water Shuriken hold has a flare of size 45 on a shape 49
  across: drawn as read it was 2,140 across and tinted the whole screen teal for as long as he held it, and only
  the round's pictures showed it. What the game does with such a size is not known; the widest of 260 other
  flattened shapes over five fighters is 193 (Charizard's roar).
- A grey picture that is opaque but for its outermost ring of pixels is read as a mask (its brightness is how much
  shows; `effect_shapes.opaque`, `BORDER_PIXELS`) when it is joined with others or flattened on a shape. Ultimate's
  flares draw `ef_cmn_grade00` on their disc, opaque but for that ring (219 of 255); read as a picture with an
  alpha of its own, every flare laid over the fighter normally was flattened into a dark disc: Incineroar's Revenge
  darkened half the screen, and Wolf's reflector, Duck Hunt's can and Charizard's Fly carried the same. A picture
  drawn alone is stored by its own alpha as before (Duck Hunt's clay shards have a clear ring and would change).
  Of the 299 grey pictures in the seven effect files of five fighters, no other is read differently by it.
- A voice played by a SEQUENCE (`PLAY_SEQUENCE`, read as a hash: `seq_<fighter>_rnd_` + attack, smash,
  special_s, special_h ...; named by length and crc32) stands for the fighter's voice lines of that occasion
  (`vc_<fighter>_special_h01` ...). Unnamed, the dresser plays nothing for it and the move is silent of his voice
  while its samples sit in the bank unplayed (verify 7.1's "in the bank and played by no script"). The reader names
  them from `names.SEQUENCE_WORDS`, and a special's is given the first line of its occasion, a stand-in for the
  pick (`voice.name_sequences`; the driver's log and `report.json` `voice_sequences` say which, or that the bank
  has no line of that occasion). The others (the normals' `attack`) keep the donor script's voice cue, which picks
  too. A `PLAY_SEQUENCE` still a hash in `game.json` is an occasion the list lacks: find it by trying the fighter's
  own voice words (`vc_<fighter>_<word>NN`) and add it (Wolf's `0x16ac2320b7` is `attack_a3`, his third jab's,
  found 2026-11-13 by trying `attack_` and every two letters; nothing longer of 17 million names fits).
- A normal whose voice the game picks from a set (`seq_<fighter>_rnd_attack...`: a jab's, a tilt's, an air attack's)
  plays the donor's own pick (`Random Smash SFX`, command 18) on that frame, where the bank holds the fighter's
  attack lines (`oneshot.dress`). The own route writes the normals anew, and until 2026-11-13 they had no voice of
  his at all. Read it in the report's `dressed` list: `voice N (picked, for seq_...)`.

## 8. Differences to name, not hide

Whatever the engines do differently and no data can change: how knockback scales, hitlag, what an air
dodge leaves you able to do, shield behaviour, ledge rules. One list, given with the port.

## 9. Checking, before anyone else plays it

- A picture of every move facing each way, on the frames its hits come out, looked at one by one.
- How many frames each common action lasts, counted in the game against the source's number. For the ordinary
  moves (jab to ledge attack) the frame he may act on is read back from the built script beside the game's
  (`verify`, from the report's `moves`); the game counts frames for the states the port's own code runs (a
  special), and the first time a rule of the driver is new.
- Each hit landed on a target at its near and far reach; grabs at their reach. Aerials are landed out of a
  short hop onto a standing target, the up aerial onto one that has jumped; never onto a target held in the air.
- The installed scripts read back and compared with what was meant. The route's report holds each ordinary move
  as built beside the game's (`report.json` `moves`: length, first hit frame, hitboxes, damage, the frame he may
  act on), and `verify` reads it: a sweep of the normals in the game then finds nothing the table did not say
  (Wolf: 758 s, no fault). A row differs from the game's only by the driver's own rules: a drawn-out hitbox is a
  row of balls, a grab is written a frame early (it takes hold the frame after), damage is a whole number, an
  action that ends with its clip is given no frame to act on, a hit for the held victim alone rides the base
  joint.
- Each special walked through against its written description, line by line.
- To find what is systematically missing: list every script command and every table value the port
  does *not* read, and ask of each whether it matters.
- A probe that misses is checked against the live hitboxes before it is called a fault.
- What depends on being hit is checked by being hit: a second fighter, the game stepped a frame at a time,
  the pad handed to it so its swing lands on a chosen frame. Armour's frames, a counter's window and what
  it gives back were only ever right after this.
- Distances are measured from where there is room. A dash that ends at the stage's edge measures the stage.
- After any change to a rule, the fighters ported before it are rebuilt and checked again.
- The sounds are listened to by machine: the game's own sound is recorded while each move runs, and each
  sound the script plays is looked for in it by its waveform, with the frame it was heard on. (Six sounds were
  in the bank and in the scripts and still silent, and the jab had none; nothing else showed either.)
  It looks only for what a script plays: a sound that is not in the bank is not looked for, and a sample nothing
  plays cannot be heard missing (Wolf's recordings found one of fifteen). The two lists of the built files
  (section 7's first line) come before any recording.
- The face close up: the camera on the head, the standing clip stepped through a blink; and the fighter seen
  from eight sides.
- The game's speed, by the game's own clock: it times each frame's logic and drawing as a share of a sixtieth
  of a second (`look_probe.py`'s `perf` step reads it), and when the two pass 1 it drops frames. Read it for
  the port beside one other fighter and for two of the port together, against a fighter of the game's own in
  the same run (Marth beside Donkey Kong: 0.20; each 1,000 matrices a costume loads adds about 0.06). The
  frame counter in the corner of a picture says the same more coarsely. (Duck Hunt ran at 30 to 46 frames a
  second from his first boot, and it was put down to the test machine until Ike was run beside him.)
- The probes' limits. `sheet_probe.py` ends itself at 110 seconds plus 14 a move: ask it for ten moves a call at
  most. `look_probe.py` ends itself at 100 seconds plus 9 a test, 20 a new match, and PROBE_EXTRA: called by hand
  under a limit of 280 seconds, ask it for at most nineteen tests with no new match (the round sets its own
  limit). `look_probe.py`'s step words are in its code, not its heading: a button with `+` or `-`, `stick x y`,
  `neutral`, `turn`, `freeze`, `unfreeze`, `step N`, `steplog N`, `pads a b`, `bag dx dy`, `pin`, `unpin`,
  `bagpercent N`, `percent N`, `fill`, `place x y`, `lift d`, `closeup distance height lens yaw`, `shot name`,
  `perf`, `attrs`, `vel`, `model group choice`, `metal`, `tint`, `untint`, `gfx N`, `hud`, `end`.
- A target is only where it is drawn when it stands on something. A standing fighter "pinned" in the air is put
  back on the floor by the engine each frame, and its hurtboxes are on the floor (a hit meant for the ground
  landed on a target pinned 22 up). A hit that only happens in the air is tested by turning the move onto a
  standing target, or against a target that is really in the air (a jump, a platform).
- The pad in a probe. `neutral` lets go of every button: a button that must stay held is followed by
  `stick 0.5 0.5`, not `neutral`. Giving the pad to the second fighter takes it from the first: a move that
  needs both (a reflector held while a shot arrives) is set up with something slow thrown first (Mario's
  fireball).
- The game stopping in a probe is run again three times on the same disc before anything is changed. A stop
  that repeats is a fault of the port. One that does not is written down with its disc, its test, its step and
  frame and its stack by function name, and counted against the stepped runs made (Wolf: two in about seventy,
  both stepped with two fighters, neither seen twice). It is never dropped, and never "fixed" by a rebuild: the
  disc is kept until it has been run again.
- A probe move says which states it is there to reach, and a run that never reached them is not a pass: read
  the states in its log. The probe's knock-down (a forward smash at no damage) only makes a heavy fighter
  flinch, so no getup and no tech is played: give him 15 per cent and room to land on the stage first.
  `step_ledge_climb` holds the stick up, which is the ledge JUMP; the climb is `step_ledge_up`.
- A line that was looked at and is not finished is recorded as open, with what is owed. Left out, it reads the
  same as never looked at.
- Facing left in a probe: `turn` is a short DASH, and a press while it runs (or into a game frozen during it) is
  not taken; use `face -1` (turned where he stands, at once). `bag` goes in front of him as he faces at that
  moment: put it after the turn. A special aimed on a diagonal is pressed with the stick straight up and aimed
  after: a diagonal held as B is pressed is the side special. (Four of Greninja's left-facing tests never started
  their special.)
- How long a short state lasts is read a frame at a time (`steplog`), never from timed pictures or the probe's
  list of states: a picture asked for at a time lands some frames later and the list is polled. (A form's
  11-frame leaving clip read as three frames from them; stepped, it was eleven.)
- A probe changes the game's own lists (the stage-particle kill, anything that relinks or frees) only with the
  game frozen (`framestep.freeze`, then two drawn frames), never while it runs: the game's update changes the
  same lists every frame and the two race. Unfrozen, the kill went round a loop in the particle list in 2 of 6
  boots and lost the particles the game made while it walked in 2 more; frozen, never (G19: the rare stops drawing
  in Hydro Pump, Cross Chop, Wolf and Duck Hunt, seen only under load). `look_probe` reads the lists again while
  still frozen and says `PARTICLES AFTER THE STAGE KILL` when anything is wrong. A stop that comes only under load
  is looked for first in what the probe itself writes into the game.
- Every test of a special names its scripts in `audio_check.SCRIPTS`: a test not named there is heard by nobody,
  and a voice it plays is passed over without a word (the sound check prints `not listened for`). Shulk's four art
  voices were written down as "not in his voice bank" while his bank held and his scripts played all four: no test
  of his listened.
- A sound only the port's own code plays (an item's, a state's own: Ittle Dew's bomb as it bursts) is named under
  the test that makes it in `audio_check.ENGINE`: no script plays it, so nothing listens for it otherwise.
- Before calling a miss, put the target where the move's boxes are: the sign of a box's place and its angle say
  ahead or behind (Fishbunjin's down smash flops onto his back and strikes behind him; a target ahead of him took
  nothing).
- A rerun of only what a round found boots once for those tests: `harness/round.py <work> <iso> <fighter> --own
  <tests> --from <the first> --no-portraits`. It overwrites `<work>/round/`: copy that first.

## 10. A second source game (what Brawl changed, and what it did not)

Ike was taken from Brawl with the same driver. Nothing in sections 1 to 9 changed; where each fact lives did:

| What | Ultimate | Brawl |
|---|---|---|
| A move's hitboxes, grab boxes, throws, free frame | the fighter's script file | the fighter's moveset file, an action a script |
| Untouchable frames of dodges, techs, getups, ledge actions | three places: a table a fighter, a table all share, a list by clip | each action's own script |
| The fighter's numbers | a table of names; jumps given as heights | Melee's own table, grown: copy by meaning |
| Numbers a special's code reads | a table of hashed names | a table per special under the game's own names |
| Skeleton and clips | one clip an action | several clips for some actions (below) |
| Sounds | banks a fighter, sounds named for what they are; a script plays a name | one archive for the game, many sounds only numbered; a script plays a number |
| Costumes | a folder a costume, the same texture names | a file a costume, the same texture names |
| Two versions of a move | a second script name | two scripts under one name |

What a new source game needs, then, is a reader and nothing else: read its files into the shapes the driver
takes (a fighter's actions with their frames; a skeleton and clips), under the names the driver's tables know.
`echo_brawl` is about 1,700 lines (moves, clips, sounds, textures, what the model shows) and the driver gained
one argument.

Finishing him (specials, voice, six colours) changed no rule either, but it found six places where the rules had
only ever met one game's answer, each now a line above: armour a frame late, a full charge that is its own
script, a counter's own multiple, a dash nobody braked, an air up special that fell before it rose, and a
ripped body that was the second costume.

Going back over what was first given as "not done" found more, and these were faults in every port, not in Ike:
every timed action was a frame short (Melee enters most actions a frame into their clip), a jab that is a punch
was silent (its swing is a sound all fighters share), sounds added to a bank were never reached, and a loop in a
script was read once. Each is a line above, and the earlier fighters were rebuilt.

Lines this added to the list:

- **Clips that are one action in the target engine but several in the source** (a smash's wind-up, hold and
  swing; an up special's start and rise). Join them, shift the later clip's script frames by the earlier clips'
  lengths, and put the charge where they join. A clip of N frames hands over after N - 1 (checked against a
  published hit frame; one frame off otherwise).
- **Fix the frame convention against a published move before trusting any frame.** Brawl's scripts count waits
  from frame 1; Ultimate's name frames outright.
- **Use a fighter that is in both games to line up tables** (Marth is in Brawl and Melee: his rows gave the
  meaning of every column that was copied).
- **A script may call one that every fighter shares** (item swings, a broken grab). The fighter's file only
  names it; decide whether the donor's own covers it.
- **The same bone can be named differently** (HipN, Hip). Rename to the names the driver's tables know rather
  than teaching every table a second name.
- **Which targets a hit strikes** is two bits of a Brawl hitbox's last word (those on the ground, those in the
  air).
- **An effect is a number**: its place in a file's list, and above that which file (the shared one, or the
  fighter's own). The lists give the names.
- **A body flash is a script event** (a colour, a change into another over some frames, off). A light thrown
  from one side is another event, and is not carried.
- **A game with no archive is written out by its reader in Ultimate's shapes** (Slap City, a Unity game: its
  reader is `echo_slapcity`): the body a costume folder (nusktb, numshb, numdlb, numatb, nutexb), a nuanmb clip
  under each of Ultimate's stems, the sounds as WAVs under Ultimate's words, the series picture and fanfare, and
  `game.json` (the moves, the numbers, the hurtboxes), the game named in `fighter_port/source_game.py`. The route
  reads those files where it read the archive (`source_game.written`) and no stage is taught the game. What every
  Ultimate fighter has and the game lacks is the reader's to write (a `Throw` bone: section 11).
- **A move given as WINDOWS** (stretches of frames, each naming its clip stretch, the next window, the frame he
  may act from, its cancels and the hitboxes out in it: Rivals 2's `ATT_` blueprints) is cut into PARTS, one
  Melee action each: the first window's path along Next (stopping at a loop, at another part's window, and at
  the game's own helpless fall and special landing), and one part for each window only a cancel reaches. A press
  is the next jab, a release a charge let go, a landing the move's landing part, a grab CatchWait; a cancel on
  the game's own condition is the module's. Each part's clip is MADE one clip frame a game frame from the
  windows' stretches, so its frames are the game's. Write the frame rule down (Rivals 2: a window's frame 0 is
  the move's frame start + 1) and hold one move against published frame data (`echo_rivals2/gamedata.py`).
- **A game in Unreal Engine** is read through CUE4Parse with the game's own mappings (`.usmap`, dumped once from
  the running game) and Oodle: the skeletal mesh and clips as ActorX (psk/psa: a non-root bone's quaternion is
  stored conjugated), a blueprint's class default as JSON, hurtboxes from the physics asset (sphyls on bones; leave
  out those the character data marks inactive, temporary or intangible at rest). Write down the axes (Unreal: Z up,
  X ahead, left-handed) and the one matrix into the port's, checked on a picture of the fighter standing
  (`echo_rivals2`).
- A written game's `time_keys` stop on the frame BEFORE the move's cancel frame (the driver plays the clip on past
  it and frees the move there): keys to the clip's end free every move at its clip's end (verify 2.2). Its sounds'
  `also` names are Ultimate's whole names with their number (`vc_<f>_attack01`): the donor's table takes some in
  number order and finds no plain word.
- **Sounds in a middleware bank** (FMOD, Wwise): look for a decoder already on the machine before the sounds stage
  (the NuGet cache holds Fmod5Sharp: `echo_rivals2/fmodtool`), write each sample by its own name, and READ which
  samples a move's sound is: the game's own sound table (Rivals 2's `SFX_<Fighter>`, then `SFX_Universal`: a
  SoundName to its event) and the bank's event table (`uetool fmod-events`: CUE4Parse's FMOD reader resolves each
  event to the samples it reaches, named from `Master.strings.bank`). Matched by name, the first Zetterburn build
  gave the plain swipes another set's samples and two voice events stand-ins (`echo_rivals2/sounds.py`). An event
  that picks one of several samples gets its first (say so); a skin's own variants are never it.
- **A new game's reader is written by READERS.md** (the order of work, finding a fighter in an engine's store,
  the fields of `game.json`), and what it wrote is checked before the port: `python -m fighter_port.reader_check
  <root> <fighter>`, which preflight runs for every written game. A number under a name the app does not know, a
  roll the clip leaves in place, time keys past the cancel frame, an `also` name with no number, no `Throw` joint,
  a body lying down or facing away: each was found only later in a trial, and each is a problem there.
- **A reader is written around its first fighter until a second one is ported.** Slap City's took Ittle Dew's move
  names, clip names, armature name and unit, and read only the kinds her moves had. Read every fighter by the
  game's own tables (its input table says which move is which), and read every kind a move can have: moves a
  special goes on to, air forms, the lists a custom call references, armour, a throw that hits by a hitbox, a box
  with no end (it ends with its move). List the roster with each fighter's input table before picking one (a
  story-only form is not a versus fighter). After a reader change, run the reader again before the driver: the
  driver builds from the `game.json` on disk. (Fishbunjin, the second Slap City fighter: first disc at 16.5
  minutes against Ittle Dew's 56.4, 13 of his 23 gaps the reader's.) Bone names vary too: use the game's bone
  references for missing landmarks, preserving an existing mapping (Business Casual Man's hands differ from
  Ittle's fists). A move that unconditionally shares a clip on the ground and in the air needs both stems;
  keep distinct air clips and do not guess conditional starts. Slap City's `--list` lists the roster's input
  tables without an export (READERS.md).

## 11. A fighter on its own skeleton

Every port up to Ike stood on the donor's skeleton: its clips were retargeted onto the donor's bones and its
body was skinned to them. That holds while the fighter is the donor's shape. Duck Hunt (a dog on four legs with
a duck on its back, ears that swing) was the first to keep its own: the game's skeleton, body and clips go in
as they are, and it is the donor's *data* that is rewritten to fit them. For a port on the donor's skeleton
every line here is "not applicable".

- Which route, decided first. The donor's skeleton when the fighter is the donor's shape; its own when it has
  limbs or parts the donor has no bones for. Its own must fit the engine: 140 joints, a clip of at most 0x8000
  bytes, joints no deeper than 29, 15 hurtboxes. Count before starting. The source's bones and their depth are
  in its skeleton file (`model.nusktb`, read with `ssbh_data_py`: Wolf 105 and 16, Duck Hunt 85 and 11) and its
  hurtboxes in `hit_data`; the real counts are known after `prepare`, which adds helpers and the engine's own
  joints (`rig/rig-<fighter>.json`: the length of `order`, and `provenance.depth`), and clip sizes after the
  clip bank is made. `verify` holds all four against the limits.
- First, before anything else is built: does it stand in a normal disc? Standing, walking, running, a jump,
  a landing and a crouch seen in pictures, and the fighter seen from eight sides. Everything below was found
  getting to that.
- The rig keeps every bone of the source in its own frame, in the source's order, so a clip is copied and a
  hitbox keeps the bone and offset its script names. What the engine cannot hold is mended with a joint put
  *above* the bone, never by changing the bone: a bone whose turns pass through the angle where three-angle
  turns lose a direction gets a helper holding a fixed turn.
- The body is the game's own model as it stands at rest, with its own weights. What rest hides comes out of it
  first (the line in section 1), and nothing is re-skinned.
- Every table in the donor's data that names a joint by number is rewritten: the engine's named joints (head,
  hands, feet, the joint an item is held by, the joint a victim hangs from), hurtboxes, the joints its
  collision box is measured from, the shield, the model's show-and-hide lists, and the joint field of every
  script command. List the tables that were found and the ones left as the donor's (the ledge box, the camera
  box). One missed is a crash or a hit on the wrong limb.
- Hurtboxes and the collision joints come from the source game's own parameters for the fighter, not from
  the donor's shape. A check of the route's own that fails on them is first held against the game's own table:
  a left and right pair the game itself gives different numbers (Wolf's knees end at 3.2, +0.4 and 3.2, -0.4,
  where every other pair mirrors to 0.0003) is the game's. It is looked at, accepted by name where the stage
  asks for that (`lopsided` in `fighters.py`), carried as it is and said. The mirror check is for pairs the game
  gives the same numbers, and another reading of the axes wins only by a clear margin.
- A body from another game has no texture animation. The donor's code still reaches for one on the texture
  slots its own data names (eyes, a face): give the costume an empty tree and a still animation on each of
  those slots, or the game stops as the match loads.
- Clips bind by position: a clip is the rig's joints in the rig's order, each with its tracks, helpers
  included. A clip over the size limit is thinned; say which and by how much.
- Who moves the fighter is decided per action from the donor's own word for it (a flag on the action): the
  clip's root travel is kept where the donor's state follows its clip, and taken out where the state's own
  physics moves the fighter. Both at once goes twice as far; neither goes nowhere.
- An action the source has no clip for holds a pose. Name each one, and what the engine would show there.
- Parts the source game swings by physics (ears, hair, tails, capes) go onto Melee's own swinging joints. What
  Melee can hold: a chain is a line of joints, each the first child of the one before, numbered in a row; its
  last joint is only carried; nine chains and eleven collision spheres at most; a joint being swung takes
  nothing from its clip; a swung joint must not be turned about its own length at rest (it stands on a
  helper). A joint the source holds stiffly to its pose is left to the clip. Shapes the source keeps chains
  out of that are not spheres become spheres; say which were left out.
- Which chains swing is an action's choice, not the fighter's: the source says, clip by clip, how much of
  each joint is left to physics (a victory pose holds the ears by hand). Carry that per action.
- The numbers of a swing are another engine's (how hard a joint is pulled back, air resistance, gravity, the
  widest angle). Map each by what it is for, take its size from Melee's own fighters, and mark it a reading.
  Then look in motion, stepped a few frames at a time through a dash, a stop, a full jump and a landing: the
  parts trail when it runs, lift when it falls, hang when it stands, and the mesh holds together at the root.
- The drawn size is one number in the fighter's data. Say what it was taken from, and what else was scaled
  with it.
- A name longer than the roster tile's plate (set it tighter before it fails the build).
- What the skin costs the game each frame. Melee skins on its own processor: its polygons come in groups, and
  every frame it blends one matrix for each weighting (a list of joints with a share each) a group names. A
  body from a newer game has a weighting of its own on nearly every vertex (four joints, shares to three
  places). Count the costume (`skin_cost.cost`: Marth's own is 387 matrices; Duck Hunt's as imported was
  8,156) and give each vertex its few heaviest joints with rounded shares (three joints, tenths: 2,927) before
  importing. Then make the costume's groups again (`skin_cost.regroup`): the importer puts each strip of
  triangles in the first group with room, so a weighting ends up named by about five groups (1,379 once each
  is named by as few as can be; what is drawn is checked to be the same, triangle by triangle).
- A fighter is drawn twice a frame: once to be seen and once for its shadow (also in one stage's reflection,
  and in the bubble that shows it off the screen). For the second the engine shows the fighter's low-detail
  pieces and hides the rest, so a fighter whose data names no low-detail pieces is skinned whole twice. Make a
  copy of the body with one joint a vertex, small pictures and a fifth of the triangles (`skin_cost.low_detail`;
  a whole copy of Duck Hunt's 17,868 resting triangles was 0.17 MB of each costume), and name both in the
  fighter's lists of pieces:
  the body as high detail, the copy as low detail, and the body again as what stays while the fighter is
  metal (the donor's metal body is gone, and the engine hides the high-detail list then).
- Every costume is built the way the first was, from its own folder of the game's files (the same model, its
  own pictures): the pieces, joints and cost must come out the same for each.
- The portrait and the stock icon. A renderer outside the game does not turn the joints the engine itself
  drives, so it cannot pose a fighter on its own skeleton (the rest pose is no pose either: a dog standing
  upright with its arms out). Take them from the game: the fighter standing, the game stopped, a flat
  background, the camera on the body and then on the head, once for each costume. The head camera's height is
  the fighter's own head joint at rest times the drawn scale, never a fixed number (set for an earlier fighter
  it gave stock icons of the tip of an ear), and the standing clip is at the same frame for every costume, or
  one square does not find every head. Look at the sheet of them before the last disc. A costume that changed
  is photographed again: photographs kept from before are of a body the disc no longer holds, and a cut mended
  by hand is lost when the stage runs again.
- The clips that live outside the fighter's own files: the results screen's and the character select
  screen's are files of the donor's, made for the donor's skeleton. Say what the fighter does there.

- **A face made of whole parts.** A newer game keeps several meshes for one place (an open eye and a shut
  one, a closed mouth and an open one, folded wings and spread ones) and each clip says frame by frame which
  are drawn. Carry every part some clip draws as a piece of its own, named in the fighter's lists of pieces as
  groups of choices: parts never drawn together are choices of one group, parts always drawn together are one
  choice, the body is the first group. Count first: the engine holds ELEVEN groups (it stops the game at
  twelve) and 124 pieces.
- The defaults are the resting face, set in the fighter's load code; a group with nothing up at rest rests on
  "none". The donor's own code sets its own groups' defaults when the fighter comes back, so they are put
  back. Every change of action returns every group to its default: a script says only what its clip changes.
- Every action's script switches the groups on the frames its own clip says, through the clip's time keys,
  and the donor's own model commands come out of every script (they name the donor's groups). The rows of the
  fighter's other table (the results screen) are actions too.
- A part a clip does not name is left to the resting clip, which runs on a clock of its own through every
  action (the standing blink). That is per-frame code, not a script: a script starts again with its action,
  and the first blink can lie past the standing clip's end.
- Say what the shadow's pass draws for a switched part (here nothing: the low-detail copy is of what is drawn
  at rest), and name the same groups in the "body while metal" lists.
- **What the body costs in room.** A hidden piece costs no frame time but is in the costume file, and a
  fighter's files share one heap with the stage and the other fighters (6.6 MB in a match). Count the source
  model's triangles against the engine's own fighters' (a few thousand: a body of thirty thousand is a costume
  three times the size of the game's largest). Read the heap with the fighter beside the largest of the game's
  own, and with two of the fighter in two costumes, on the largest stage; make pictures smaller before
  anything else.
  Room is a sum of file sizes, done before any disc (`verify`): the heap is 6,599,680 bytes and holds each file
  whole, plus 96 bytes a file: the fighter's data and its effect file, each costume once a colour, the stage
  (Final Destination 611,136; Pokemon Stadium 2,411,424 with what it loads beside itself) and the other fighter
  (Peach, the largest of the game's own, 1,084,768). Three matches are held: two of the fighter in two costumes
  on Final Destination, the same on Pokemon Stadium, and the fighter beside Peach on Pokemon Stadium. The sum
  is the game's own reading to the byte (Wolf at 1.8 MB a costume: 1.85, 0.05 and 0.77 MB left; at 3.4 MB none
  of the three loads). Where the bytes are: the `costumes` stage prints each costume by kind (pictures by format,
  display lists, the rest) and stops at one too large for the heap. A picture with soft edges (fur) is held at 16
  bits a pixel where a plain one or a cutout takes 4: four of them were 2.1 MB of that 3.4, and they are made
  smaller first. Then triangles: a body from a newer game has ten times a Melee fighter's. The shadow's copy
  keeps a fifth of them (`skin_cost.low_detail`) and the parts rest hides keep half, each island of their
  picture on its own so no picture slides (`skin_cost.fewer_hidden`, a stand-in, said in the body's receipt;
  each new corner takes the picture place of the old surface under it). Painted detail on a halved part bends a
  little across the larger triangles: the duck's open wing shows faint light streaks in its feathers when the
  picture is blown up three times, and reads as the wing at game size. Look at the largest halved part that
  shows in a move (`fewer_triangles` in the receipt names each part and its triangles) before calling it done.
  Duck Hunt's pictures were small already (0.43 MB, every one compressed): his room was in triangles, and these
  two took his costume from 1.81 to 1.41 MB and two of him on Pokemon Stadium from 0.38 MB over to 0.41 MB
  under. The fighter's data counts too, and the things its specials make are in it (Duck Hunt's is 0.69 MB to
  Wolf's 0.27; the 0.49 MB once read as free for two of him is what was left at the file where the loading
  stopped). The game is asked once, at the end of the round (`harness/round.py` ends with the three matches,
  each with its picture: a match that does not load ends the boot there and says so).
- A vertex the source gives no normal: mend it and say how many.
- Check a face in the game, close up: every choice of every group once, the standing blink, a hit taken, an
  attack that opens the mouth, a jump, metal, a second costume, and that nothing is drawn twice. The probe has
  the moves: `PROBE_FACESHOT=1 PROBE_CLOSEUP="<distance> <height> <lens> <yaw>" look_probe.py <iso> face_blink
  face_fsmash face_jump face_hit face_metal` photographs every stepped frame on which a group's choice changes,
  with the choices in the picture's name. The camera stands at (sin yaw, cos yaw) of its distance from the
  fighter (50 is his right front when he faces right): aim it at an eye that is drawn, not one under a patch or
  a fringe, and set its height from his own head joint, not the last fighter's (`look_blink` parks its own
  camera at an earlier fighter's head, and takes no picture at all unless `PROBE_STEPSHOT` is set). For the hurt
  face take the hit from far off (a shot): a big fighter's smash fills the picture.
- The game's files come out of its archive by the repo's own call
  (`echo_ultimate.gamedata.arc.fetch_fighter(root, fighter)`: about a second, some 470 files: the models, the
  first costume's clips, the parameters), never by hand, and every stage that reads them fetches them first: a
  fighter nobody has extracted before is no different from the last one.
- The donor is Marth for every port on this route until a second donor's tables are measured (`own_data.DONOR`,
  `own_skeleton.DONOR`, the driver's `*_DONOR` tables: its joint lookup and tree, weapon joints, the joints its
  block of numbers names, rest height, the numbers of its special states). Say so, and say which Melee fighter
  is closest by how the fighter fights and what its states would have saved (Wolf: Fox, for a blaster, a
  reflector, a dash and an aimed flight; on Marth each is code written from nothing).
- What a port is told about one fighter is in one place (`fighter_port/fighters.py`), and the command's first
  stage (`preflight`, seconds) says which values were given, which it worked out and how, and which are not there.
  The engine's 54 named joints are bound by bone name; which digit is the thumb is measured on the rest pose,
  never assumed (Wolf's is digit 5, 29 degrees off the other four). The joint an item is held at, the taunt,
  hits the game's code times, parts its code shows and hides, a weapon that is a second model: each is written
  there only where the game's files cannot say. The specials are a module of the fighter's own
  (`own_<fighter>.py`, started from `own_template.py` with `SPECIALS.md` as the guide); without it the port
  builds the shared template. Slap and Rivals add supported source movement, branches and articles;
  inspect the package's explicit remaining mechanic limits. Other readers retain clip/hitbox placeholders.
- A run does again only what changed. `prepare` keeps the rig and the body while their inputs are the same (they
  are two to three minutes of it; the log says `kept` or `made again: <what changed>`, and deleting
  `<work>/rig/made-from.json` or `<work>/body/made-from.json` makes one again anyway); the clip bank is kept in `<work>/bank/cache`, and a rerun makes only the
  clips whose job changed (the first bank about four minutes, a rerun under one); after the first disc a change
  to a special is the driver and then the disc (`--only driver`, then `--from firstdisc`), and a change to the
  body is `prepare` on. What a stage needs of the fighter is asked before anything long (`preflight`), all of it
  at once, not one fault a run.
- List the source's joints that no clip moves and the skin still uses (`H_...` in an Ultimate model: Wolf has
  ten, at hips, knees, shoulders, elbows and wrists, and eight carry 589 of the skin's weights). The game turns
  them from their neighbours by rule (`model.nuhlpb`), which the reader does not apply: in the port they stay at
  rest on their parent. Bake the rule into every clip, or give their weights to the joints either side, and say
  which. Look at shoulders, elbows, wrists and knees close up in a move that turns them.
- The heap probe's "in the match" is not proof that the match loaded: open its picture. A match that did not
  load shows the stage select screen or black, and its "free" figure is what was left when loading stopped,
  which reads as room to spare (two Wolves at 3.4 MB a costume "had" 2.2 MB free, and the game hangs for any
  player who picks them). The probe's own second fighter and stage are not the worst case: name Peach and
  Pokemon Stadium.
- A source's table can name the model's own root, which no skeleton file lists (`top` in an Ultimate table: Ivysaur's
  collision box hangs a corner on it): it is the rig's top joint (`own_data.SOURCE_ROOT`). A table can also give more
  collision-box joints than Melee's six (Ivysaur gives eight): keep the ones that make the box at rest (the
  highest, the lowest, the furthest back and forward), then the rest in the source's order up to six, and name the
  ones left out (`own_data.ecb_six`; the fighter-data report's `ecb.left_out`).
- A source over the joint limit is made to fit (`own_skeleton.py`, "a skeleton over the engine's joint limit"; only a
  rig within 15 helpers of the limit): bones that cost no pose are folded into the bone above (no skin, or no clip
  moves them, and the engine binds nothing to them: their skin and script names go to that bone); a scale helper
  only where the parent's scale is uneven; then, a stand-in, the turn helpers of unskinned bones and the leaves with
  the least skin are given up, the face last. Each is named in the rig's provenance (`folded`, `scale_exact`,
  `over_limit`): look at what was given up in the game. (Incineroar: 143 bones, 187 joints asked for, 140 made.)
- More groups than the engine's eleven: a part up at rest is drawn ALWAYS, or two groups are joined, whichever is
  wrong on fewer frames; two groups both up at rest are never joined (`own_faces.plan`). Say which.
- A reading of the hurtboxes is weighed capsule by capsule as well as by the body's points (`own_data.capsule_check`,
  `capsules_inside`): one dense part (a big head, fur) must not outvote the limbs. Another reading overturns the
  game's only by winning both.
- Before a plain first disc (no module), name which of the four plain specials the fighter's clip names leave NOT
  BUILT (a special in parts, `specialsstart`, `specialhistart`, is never `specials`): such a disc does not pass
  `verify`, and the module is owed before the round.
- A clip may carry tracks for bones the skeleton does not have (Shulk's `S_Hip_hit` on 318 of 359 clips, in no
  model file). They move nothing the rig has: every reader passes them over (`source_preflight.ANY_BONE`: the
  bank, the rig's survey of clips, the shield pose) and the bank's report names them (`unbound_tracks`). A reader
  that refuses a clip says so in its stage's log; the rig made from 20 of 359 clips said nothing.
- The sword trail on the fighter's own skeleton is the game's (`own_route.own_trail`): Melee draws it along its
  joint's x axis from that joint's place (ftafterimage.c, column 0 of the joint's matrix), and the game gives the
  blade's ends on a bone whose blade may lie along another axis (Shulk's `haver`: along y). It goes on the weapon
  bone at or under that bone whose x lies along the blade (Shulk: `swordr`, joint 77, 2.6 to 18.6), never on a
  blade joint the clips open and shut. The colour is the trail picture's, per move where the game draws a move in
  another picture; the trail runs only where the game's script turns it on (the route carries the swing effects
  itself). The report's `trail` and the log's `sword trail:` line say where. In the game, the probe's `trail` step
  reads it (points held, the span Melee copied from the description, the joint's place and axis): `sk_trail`
  read 3 points over 2.637 to 18.637 through Shulk's down smash and none after frame 45; look at one swing too.
- The shield hangs from the throw slot's joint (Marth's 88, Ultimate's `Throw`), and Melee SCALES that joint to
  the shield's size every frame (`ftCo_Guard.c:ftCo_80091D58`): it must be a joint with nothing under it. A
  source with no such bone gets one from its reader (`echo_slapcity/transcode.py`, THROW); without it the slot
  falls to the engine's YRot (`own_data.joint_map`, tier ANCESTOR) and the whole body grows with the shield
  (Slap City's Ittle: six times her size behind a full shield, with `verify` passing then). `own_data` now says
  in its report which joint the shield hangs from and what is under it (`shield`), and `verify` 11.42 calls any
  joint under it a fault. Look at the round's shield pictures: the body the same size as when standing.

## 12. Everything outside the fight

A port that is right in a match still says "the donor" everywhere else. None of this is in a move script, so
no reader finds it: go down this list. For each line: the fighter's own, a stand-in that is said, or the
donor's and said.

- **Series emblem**, behind the damage and on the results screen. It is a flat MODEL, not a picture: a series
  added with only a picture shows a piece of the picture's shape. Cut the model from the source's series
  picture (holes and all, wound the way the engine's own are) and look at it in a match.
- **Victory fanfare**: the fighter's own if the source has one, else its series'. A music stream may be in a
  codec nothing here decodes; its packets can be rewrapped for a decoder that is here. Heard by recording the
  results screen, beside a recording of a disc without it. A series' fanfare is named for the series' first
  fighter, not for the series (`bgm_z07_f_fox` is Star Fox's; nothing answers to `starfox` or `wolf`), and the
  stream names are in no list, so each candidate is tried: the fighter, the series, then each fighter the roster
  puts in that series. Say which stream was taken; where none answers the donor's plays, and that is said.
- **The results screen**: three winning clips each with its wait, the clap of a loser, the pose when chosen.
  They are in a file of their own made for the donor's joints; a fighter on its own skeleton is twisted by
  them. Test runs may skip this screen (a netplay build's own code does): take that code out for the look.
  A clip there may be longer than a match's (its own size limit).
- **The one-player screens**: the "versus" card's pose, the trophy falling at the end, the standing pose in
  cut scenes. The first two are asked for by name from a file the port must add, or the donor's clip plays
  on the fighter's joints.
- **Name** on the results banner, under the portrait, on the roster; **announcer** on the roster and for the
  winner.
- **Team colours**: which costume is the red, the blue, the green one.
- **What the one-player modes give**: its target test, its trophies, the pictures and the film after a win.
  They stay the donor's unless made; say so.
- **Being copied** (Kirby's hat and copied special): the donor's unless made; say so.
- **What other things do to it**: an item held (at its own hand), a hat or a flower put on its head (the
  places are numbers measured from the donor's head), the block of ice and the egg it is shut in (sized for
  the donor), the bubble it is shown in off the screen, its shadow, its metal form, growing and shrinking,
  being held and thrown by every other fighter.
- **The computer player** plays the donor's habits with the fighter's moves. Say so.
- **The crowd's chant** and anything else the engine picks by the fighter's number: look for a table in the
  engine indexed by fighter before saying there is none.
- Start a one-player mode with the fighter once and look: its own character screen, the versus card, the
  first fight loading. A versus match exercises none of them. `classic_probe.py` takes the tile's place with y
  turned over: the project's css.json value `y: 2.0` goes in as `-2.0`.
- **Kirby copying the fighter must not stop the game.** A port made from a donor carries the donor's entries
  for Kirby, and those name the donor's own hat code, which reads the DONOR's hat: loaded only when the donor
  is in the match. With any other fighters the game stops as Kirby puts the hat on. Have Kirby copy the
  fighter in a match without the donor (a Classic fight against Kirby does it at the very start). Until the
  port brings a hat of its own, clear the entries: Kirby then gets nothing from it and keeps his own special.
- The win poses play their own sounds on the results screen. The source may name a sound it plays there
  after the pose (`..._win01`): it is the same sound, so the place the bank already has for it will do.
  Heard by recording that screen.
- A name wider than the roster tile's plate even set tight (a group's: POKEMONTRAINER): the plate says one
  word of it, the last first (TRAINER), else the tile keeps the plain crop; a name never stops the build
  (`harness/roster_tile.plate_words`). Say which word the plate shows.
- The portraits are photographed with the camera set from how tall the body is drawn as it stands (its own
  points), not from its tallest joint: a head above the last joint (Squirtle's, over his jaw) is otherwise cut
  off at the top of the picture, where the emulator also writes its messages ("Wrote memory card A ..."). What
  is not joined to the fighter in the picture and is small (a speck, a letter) is not cut out with him
  (`game_art.drawn_height`, `game_art.subject`). Look at the sheet: a flat top on a round head is a cut.
- A series picture of thin lines (Xenoblade's rings, one to three pixels wide) is cut again at twice its size, or
  its lines come out with no width; the receipt says which (`larger`). A cut of a few thousand triangles is more
  than the game's own emblems: look at it in a match.
- A game with no announcer: the fighter is called by the line the app gives a fighter without a call, "Bonus
  Character" (`core/narrator.build_bonus_clip`, spliced from the project's own banks; `make_sounds.py` makes it
  when the sounds give no `announcer.wav`). Left alone, the donor's call stays and the fighter is announced as
  the donor. A series picture that is a card (a name's letters on a scene) is cut to its letters for the emblem
  by its reader, or the emblem is the card's outline.
- A game read by a reader of its own (`echo_<game>`) has no archive to look in: the reader finds the emblem, the
  fanfare and the name call where the fighter's own data names them and writes them in its identity folder
  (`source_game.py`). Rivals 2's character data (`Char_<Short>`) names all three: its element (the character
  screen's emblem, `menus_css_emblem_<element>`), its arcade data's `VictoryJingle` and its `AnnouncerLine`, both
  FMOD events whose samples the banks' event table gives (`echo_rivals2/identity.py`). Take a sample from the
  smallest bank that holds it (the fighter's own holds his fanfare; the music bank is 69 MB). A series every
  fighter of the game shares with a picture that differs by fighter (Rivals' elements) is said in the receipt.

## 13. A fighter of forms

A fighter that is two or more fighters, one at a time, switched in play by a move (Pokemon Trainer's three; Zelda
and Sheik). Each form is a whole fighter: every line above is answered for each form. These are the lines the
group adds.

- What the recipe is told about a group is one entry in `fighters.FORMS`: its forms in the order the switch goes
  round (the first is the one a match starts as), the special that switches, the clips that end a form and begin
  the next, the published timings the game's files do not hold, the announcer's call. `port <group> --own` ports
  every form by itself (`<work>/<form>`, each on its own skeleton with its own normals, movement, costumes and
  specials) and then links them onto one disc. No form's code names another.
- The switch's states are the FIRST states of each form's own, so they have the same numbers in every form: one
  form's code puts the next in its arriving state by number. The switch special is left out of the form's
  specials (`ctx['switch']`: the template leaves it out; a form's own module must too), and the variables the
  switch keeps (`forms.PARKED`, `forms.CLOCK`: the last fighter variables) are used by nothing else.
- The switch is Melee's own transformation (`Fighter_Transform`, Zelda's and Sheik's): damage, stocks, place,
  facing, speed, ground or air, shield and a held item go with the player. The input block goes too, the press of
  the switch with it: the arriving form spends it (`input.timer_speciallw`), or it switches again on its first
  frame and again until the game stops.
- Melee keeps two fighters a player. A third form is made the first time it is needed, and making a fighter whose
  files were never loaded stops the game, while Melee loads only a fighter and its one partner: the disc carries a
  code that loads every form of the ring as the match loads (`forms.preload_code`, at the end of the loader the
  match asks once a player). A form made after GO has its inputs off until they are turned on (`ftLib_8008688C`).
  The one a third form displaces is kept aside (never unloaded: unloading empties the player's place), and the
  next form is found in the game, from m-ex's table of partners. Asked of the game: a match that switches to every
  form and back to the first.
- The disc: every form in one project; each form's partner (`subCharacter`, the way Zelda and Sheik are each
  other's, behaviour 1) is the next, the last's the first; the character select screen keeps the first form's slot
  alone, named for the group (`harness/forms_link.py`, which writes `link.json`). The costume picked is a number,
  and every form wears that number: every form needs as many costumes as the first, in the same order.
- The announcer: the source has no call for a form, only for the group; every form takes the group's
  (`voice.announcer`, `fighters.FORMS` `call`).
- Room: every form is loaded with the match. In the files' heap each form's data and effects and a costume a
  player; in the clip heap (9,881,600 bytes, where each fighter's whole clip file goes) every form's clip file
  beside the second fighter's. The second fighter that costs most is Zelda, who brings Sheik.
  `verify.forms_room` makes both sums for the forms' work folders; the game is asked once, with its picture.
- What a form port can forget, each said in the build's report where it is not the game's: what comes back
  after a KO (Melee: the form that fell; the source may send out the next), the switch's own sounds and effects
  (the scripts of clips with no move script), its flashes of colour, the trainer or partner shown beside the
  fighter, a thrown ball or other thing the switch makes, the switch pressed again too soon (the source's wait),
  a held item across the switch (Melee carries it; Brawl dropped it), a switch during hitstun or on a ledge
  (Melee's own rules for a special decide), the results screen, portrait and stock icon (each form's own; the
  screen's portrait is the first form's), and a second player of the same group (two rings of three).
- How the forms are made to fit, by the port command and nothing by hand: a form's plain pictures are half the
  side of a fighter's alone (`own_skeleton.picture_side_for`); while a match of the room does not fit the files'
  heap, the form with the largest costume is made again with its pictures at half that (`forms.shrink_side`,
  `<form work>/forms-side.json`; Ivysaur's 741 KB costume came to 594 KB at 128). Each form's clip file is given an
  equal share of the clip heap beside Zelda and Sheik, and its bank is made again at looser tolerances until it
  is within it (`forms.clip_share`, `forms.looser`: a step looser makes a bank only about 5% smaller, so a form
  a third over its share is about six steps; remembered in `<form work>/bank/forms-step.json`). Look at the
  loosest form's motion in the game: a tolerance many steps looser can show as a shiver.
- Each form's portraits, stock icons and (the first form's) roster tile are cut from pictures of it on the linked
  disc, each form by its own number on the roster: a form off the character screen is still a fighter the probe
  can pick (`port` stage `art`, then `build` again). Before that they are renders made with the donor's camera,
  which on a fighter of another shape frame nothing (Squirtle's tile was a close-up of his shell).
- A third form made mid-match costs its own fighter in the game's object heap (Charizard: 281,504 bytes), not
  its files, which came with the match (the heap probe lists every form's data, effects and costume for each
  player at the loading; two Trainers on Pokemon Stadium left 0.19 MB of the files' heap, as `verify` summed).
  Asked of the game once: the memory before and after a switch to every form (`forms_room`).
- The pictures of a form are taken on a disc that holds its current costumes. A run started after the link (a
  form made again, then the group from `art`) would photograph the disc before, and the pictures, newer than
  the costumes, would be kept: Squirtle's tile kept his blank eyes after they were mended. The art stage stops
  when the disc is older than any form's costumes (`forms.stale_disc`); start from `link` then.

## Running a port, and when it is finished

One command runs the stages (a clean project, the driver, the fighter's sounds, its costumes, the package and a
test ISO), each from `fighter_port/harness`, each with its own log:

    python -m fighter_port.port ike --game brawl --donor Marth --name Ike --work <dir> --root <game files> --body <body.dat> --iso <out.iso>

Through the tool server it is `native_port` with `op: port`. Two things it never does: import the body (that
costs money: bring the body, or the owner's word) and check the result in the game.

A built ISO is not a finished port. Every line above has a number (`fighter_port.port.lines()`, or `op: checklist`),
and the port is finished when each has an answer in `<work>/checklist.json`: **done**, with how it was seen in the
game; **difference**, with what the engines do differently (these are the list given with the port); or
**not applicable**, with how that is known. `op: checklist` with a `work` folder says what is still unanswered.
An answer is recorded with `line`, `answer` and `how`. A line that was looked at and is not finished is recorded
as **open**, with what is owed: it still counts as unanswered. The answers of the fighters done so far are kept
as examples in `fighter_port/examples/<fighter>/checklist.json`, as they stood when saved (2026-11-12): Duck Hunt
132 of the 158 lines the list then had (18 of them differences), Ike 109 (six differences; his were all answered
when the list had 83 lines, and the lines added since are still owed on him). The 23 lines added after them came
from Wolf, ported cold with nothing but this repository, and are owed on every fighter before him. Copy one into
a work folder to carry on from it.
The pairs of numbers between two games are asked of the fighters in both with `harness/both_games.py`.

A body ripped from Brawl is made ready first (`--rip <the rip's zip>`: the `model` stage writes
`<work>/input/<fighter>-ready.zip`, with what rest hides taken out and the eye's layers named); that file is what
is imported, and the same rip gives the blink its lids at the `costumes` stage.

### A round: the files first, then the game once

Checking a port is a round, and a round starts the game ONCE. Every line above is marked in
`checklist_marks.json` by what it takes to answer it for a new fighter: 59 are rules of the system (nothing is run),
115 are answered from the files the build wrote, 25 from the files with one reading in the game to confirm, 13 need
the game in the same way for every fighter, and 57 need it only because of code written for that fighter (its
specials and what they make). So:

1. `python -m fighter_port.verify <work>` answers what the files can, in under a second, and a fault there is
   fixed before the game is started at all. A line marked for the files that has no check yet is listed by it.
2. `harness/round.py <work> <iso> <fighter> --own "<the fighter's test names>"` does everything that needs the
   game in one boot: each costume photographed (a new match for each, about six seconds, not a new boot), what
   every fighter is asked, then the fighter's own tests, each in a match of its own so that nothing one test left
   out is there for the next; the sound is recorded throughout and every script sound looked for in it. It leaves
   one log, the pictures thirty to a sheet, and `report.json`.
3. What it says is read against the source game, the faults are fixed, and the next round is a new disc and one
   more boot. A boot is owed only for a new disc or after the game stopped (`--from <the test it stopped in>`).

The port command runs these as its `verify` and `round` stages, and cuts the artwork from the round's pictures.
A fault the game shows that the files did not becomes a check in `verify.py`: the game is not asked the same
question of the next fighter. Sweeps (every move photographed facing both ways, each hit landed near and far) were
how the rules were found; they are not owed on a fighter whose files already answer the line.

The order to check in, with what each step cost and found on Wolf (ported cold, 2026-11-12: 55 game runs and 53
minutes in the game, made in the order section 9 lists its checks, which is not this one):

1. One boot: he loads, stands, walks, runs, jumps, lands (37 s). Nothing else says the files hang together.
2. The file checks (under a second). Two faults that the game had hidden were plain in the files: a costume too
   big for three matches (two game runs had called it a pass, and it took an hour to see), and fifteen sounds of
   his own that the game's scripts play and his bank cannot (247 s of recordings found one).
3. The specials and anything else with code of its own: stepped once, a picture each way, each hit on a standing
   target, their sounds recorded once (about 350 s, and again after each fix). Every fault of the port that the
   game showed was here or in room: 657 s on the specials found four.
4. What only the engine shows, once, on the last disc: the three room matches with their pictures (the end of
   the round now, about 20 s), Kirby (30 s), the results screen (45 s), Classic (35 s), metal and the face moves (95 s). Kirby, the results screen
   and the frame clock, run again on each of four discs, cost 339 s and found nothing: a change to a special's
   code does not rerun them.
5. Sweeps last, and only what the files cannot answer. On Wolf 1,061 s of them (every normal photographed both
   ways, frames counted, each hit landed, his numbers read from memory) found no fault of the port.

Another 595 s went to the probes themselves (a deadline, cameras on the wrong side of a head, a knock-down that
did not floor him, two stops that never came back). What a change costs: to a special, 16 to 34 s of driver and
95 s of disc; to the body, five minutes, half of it the eight costumes.

The checks themselves are scripts in the harness. `sheet_probe.py` photographs every move facing each way on
the frames its hits come out. `look_probe.py` steps the game a frame at a time and logs the fighter and a second
fighter each frame; it can hand the pad to the second fighter (`pads 1 0`) so that its jab or smash lands on a
chosen frame, and print the live hitboxes against the target (`PROBE_BOXES=1`). It also counts the frames of each
state (`steplog`), photographs each step with the camera parked close (`closeup`, `PROBE_STEPSHOT`), records the
game's sound (`PROBE_AUDIO`) for `audio_check.py` to look for each sound a script plays, and photographs Melee's
shared effects by number (`gfxcat_<first>_<last>`, sheets by `gfx_sheet.py`). A probe ends its own Dolphin at a
deadline; it must never end one it did not start (check the ISO on the command line, not the run folder).

### Mechanic inventory in ordinary packages

Review `mechanic_coverage` in `port-implementation.json` alongside special-slot
coverage. It contains reviewed character mechanics and source obligations found
by the reader: compiled branch entries, compiled article creation and custom
window conditions. Each implemented/adapted claim names a built native handler
and explains the behavior. An unclaimed obligation remains explicitly unfinished.
Successful compilation or file verification does not clear it.

Developer acceptance checks focus on playable behavior: the move works from
ground/air as appropriate, hits or captures an actual opponent, handles misses
and interruption, cleans up articles/resources, and returns control. Resource
mechanics also need gain/cap/spend/reset and powered/unpowered choices; item
batting must originate from native hurtbox damage. Verify memory admission after
adding resident article models, including a mirror matchup on a large stage.
Timing parity and cosmetic fidelity remain separate polish work. End users are
not required to run either the source-game or Melee calibration harness.
