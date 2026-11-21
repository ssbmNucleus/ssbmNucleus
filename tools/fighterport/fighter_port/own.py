"""Moves a fighter has that the donor has nothing like: states of the port's own.

The driver puts a fighter's specials on the donor's own special states wherever
they fit. What does not fit gets a state of its own (see `states`): its clips go
on donor actions the port does not otherwise use, and its logic is C in the
port's code file. That logic is the fighter's own design, so it is written per
fighter here, in terms of what the game's files say (clips, scripts, hitboxes)
plus a few numbers the game keeps in code this reader does not read; each such
number says where it is from.

  CLIPS[fighter]   {clip name: donor action, or a join}: the clips of its own states
  build(...)       -> {source, rows, load, frame, entries, provides} for the code file
"""
from __future__ import annotations

# ---- Cloud ---------------------------------------------------------------------------------------
# Climhazzard's second half: B again during the rise, and at its top Cloud turns the sword down and
#   plunges until he lands. The game's script for it (specialhi2) runs on into a falling pose with its
#   hitboxes still out, then a landing clip with a hit of its own.
# Limit: down special charges the gauge while B is held (the game: 400 frames from empty to full), and
#   damage taken fills it too (the game: 100% for a whole gauge). With a full gauge the down special is
#   Finishing Touch, which empties it, and the other three specials are their Limit versions (CLOUD_LIMIT).
# A chained side special that goes on only once its first swing has hit something (a fighter or a shield):
# the driver then writes the first step's window on a script flag the donor does not read, and the
# fighter's code passes it on to the donor's own flag once a hit has landed.
CHAIN_NEEDS_HIT = {'cloud'}
CLIPS = {
    # Byleth: the whip (up special) that hits something latches onto it. The game then plays a short clip
    #   of the catch, moves Byleth to what he caught (in code this reader does not read) and plays a kick
    #   whose hit is written as a throw; after it he is free to act. Here: the catch clip plays while he is
    #   drawn to where the whip's tip hit, then the kick, then a hop.
    'master': {
        'specialairhihit': 'SpecialAirS4Hi',
        'specialairhiovertake': {'motion': 'SpecialAirS4Lw', 'strike': 1},     # the second of the kick's three hits: the one that launches upward
        # the bow put away while it is drawn, the axe before its swing has begun (shield does both)
        'specialncancel': {'motion': 'SpecialS2Hi', 'holds': 'bow'},
        'speciallwcancel': {'motion': 'SpecialS2Lw', 'holds': 'axe'},
        # the whip caught on a wall: drawn to it, he jumps off it
        'specialairhiwalljump': 'SpecialAirS4S',
    },
    # Ike (from Brawl). Quick Draw: a crouch, a charge held as long as the button is, a dash whose speed the charge
    #   sets, a swing at the first fighter he reaches (or an end with no one in his way); five clips on the
    #   ground and five in the air. Aether: after the rise (the donor's own up special, which plays it) he
    #   plunges with the sword until he lands, where a slam plays; on the way down he catches a ledge he faces.
    'ike': {
        'specialsstart': 'SpecialS2Hi', 'specialshold': 'SpecialS2Lw', 'specialsdash': 'SpecialS3Hi',
        'specialsattack': 'SpecialS3S', 'specialsend': 'SpecialS3Lw',
        'specialsairstart': 'SpecialAirS2Hi', 'specialsairhold': 'SpecialAirS2Lw', 'specialsairdash': 'SpecialAirS3Hi',
        'specialsairattack': 'SpecialAirS3S', 'specialsairend': 'SpecialAirS3Lw',
        'specialhi3': 'SpecialAirS4Hi', 'specialhi4': 'SpecialS4Hi',
    },
    'cloud': {
        'specialhi2': {'motion': 'SpecialAirS4Hi', 'then': ['specialhifall'], 'hold': 90},
        'specialhilanding': 'SpecialS4Hi',
        'speciallwstart': 'SpecialS4S',
        'speciallwloop': 'SpecialS4Lw',
        'speciallwend': 'SpecialAirS4S',
    },
}

def _input_wrappers(ctx, motions, callback, extra_rows=()):
    from .states import iasa_wrapper
    lines, replacements = [], {}
    for motion in motions:
        if motion not in ctx['state']:
            continue
        name = callback + '_' + motion
        lines += iasa_wrapper(name, callback, (ctx.get('row') or {}).get(motion, {}).get('iasa'))
        replacements[motion] = name
    for i, row in enumerate(extra_rows):
        name = callback + '_Extra' + str(i)
        lines += iasa_wrapper(name, callback, row.get('iasa'))
        row['iasa'] = name
    return '\n'.join(lines), replacements


CLOUD = '''
// ---- Cloud's own states ----------------------------------------------------------------------
#define ST_DIVE {dive}
#define ST_DIVE_LAND {dive_land}
#define ST_CHARGE_START {charge_start}
#define ST_CHARGE_LOOP {charge_loop}
#define ST_CHARGE_END {charge_end}
#define ST_RISE {rise}
#define ST_RISE_AIR {rise_air}
#define B_BUTTON 0x200
#define CANCEL_BUTTONS 0xC70                            // shield (R, L), a jump (X, Y), a grab (Z)
#define CHARGE_AGAIN {charge_again}                     // frames into the charge before the special button ends it
#define N_START {n_start}                               // the states the neutral special starts in, ground and air
#define N_START_AIR {n_start_air}
#define N_GROUND_X {n_ground_x!r}f                      // what he keeps of his speed as it starts (the game's own numbers)
#define N_AIR_X {n_air_x!r}f
#define N_AIR_Y {n_air_y!r}f
#define LIMIT_PER_FRAME (1.0f / {charge_frames}.0f)     // the game: {charge_frames} frames of charging fill the gauge
#define LIMIT_PER_PERCENT (1.0f / {charge_damage}.0f)   // the game: {charge_damage}% taken fills it
#define LIMIT_PER_DEALT (1.0f / {charge_dealt}.0f)      // and {charge_dealt}% dealt
#define LIMIT_HOLD {limit_hold}                         // frames a full gauge lasts unused (the game's own number)
// What the gauge looks like. As in the game it is part of the player's damage display, a bar by the damage
// number that is always there: flat rectangles drawn with the game's own routine for one, by an object of
// its own on the list the display's camera draws (the game's own displays are objects on that list). On
// the fighter: a blue light that grows as the gauge fills and beats once it is full, an aura of rising
// streaks while it charges or is full, and a gleam on the sword at the moment it fills.
#define HUD_LIST 11                                     // the drawing list of the damage displays (ifstatus.c)
#define HUD_PLACE ((Vec3 *(*)(int))0x802F3424)          // ifAll_802F3424: where a player's damage display sits
#define HUD_CAMERA ((GOBJ *(*)(void))0x802F3404)        // ifAll_802F3404: the object that holds the displays' camera
#define GAUGE_X {gauge_x:.2f}f                           // the bar's left end, from the display's own point
#define GAUGE_Y {gauge_y:.2f}f                           // its lower edge
#define GAUGE_WIDE {gauge_wide:.2f}f
#define GAUGE_TALL {gauge_tall:.2f}f
#define GAUGE_Z {gauge_z:.2f}f                           // toward the camera from the display's own pieces
#define GAUGE_EDGE {gauge_edge:.2f}f
#define AURA_TALL {aura_tall:.1f}f                      // how high the streaks of the aura rise
#define AURA_STREAKS 8
#define OVER_Y (AURA_TALL - 1.5f)                       // the bar over his head while he charges: just clear of his hair
#define OVER_WIDE 10.0f
#define OVER_TALL 0.9f
#define OVER_EDGE 0.25f
#define DRAW_RECT ((void (*)(Vec3 *, Vec3 *, GXColor *))0x80009DD4)                                 // lbColl_80009DD4
#define SPAWN_EFFECT ((void (*)(GOBJ *, int, int, int, int, Vec3 *, Vec3 *, float))0x8009F834)      // ftCo_8009F834

static float limit[6];              // each player's Limit gauge, 0 to 1 (2 once it is full and has been seen full)
static float seen_percent[6];
static float their_percent[6][6];   // what each other fighter's damage was last frame (damage dealt fills the gauge)
static int limit_left[6];           // frames a full gauge has left
static u8 boosted[6];               // the fighter's numbers are the full gauge's
static u16 charge_age[6];           // frames since the charge now under way began
static u8 charge_armed[6];          // the stick has been let back to the middle since it began
static u8 was_charging[6];          // he was charging on the frame before this one
static int last_state[6];
{boost_store}
// With a full gauge the fighter's own numbers change (the game keeps a table of them: which number, times what).
static void Boost(FighterData *fd, int on)
{{
    int p = fd->ply;
    if (on == boosted[p])
        return;
    boosted[p] = on;
{boost_apply}}}
static u8 dive_asked[6];
static u8 glow_tick[6];             // counts frames, for the beat of the light
static u8 lit[6];                   // this code has its light on the fighter
static u8 aura[6];                  // 0 no aura, 1 the gauge is full, 2 it is being charged
static void (*drawn[6])(GOBJ *, int);       // the game's own drawing of each fighter: the aura is drawn after it

// The gauge, drawn with the player's damage display: a dark edge, a dim back, and the bar itself, which is
// bright and beats once the gauge is full. (Only when the camera drawing is the displays' own: an object on
// this list in another scene, the results screen say, is not theirs to draw. It is drawn in the last pass and
// after the display's own pieces, or the see-through emblem behind the number is drawn over it. The routine
// multiplies a colour by itself, so these are the roots of the colours meant.)
static void Gauge_Draw(GOBJ *gobj, int pass)
{{
    int p = (int)gobj->userdata;
    GOBJ *camera = HUD_CAMERA();
    Vec3 *at = HUD_PLACE(p), a, b;
    float full = limit[p] >= 1.0f ? 1.0f : limit[p];
    GXColor edge = {{0, 0, 0, 255}}, back = {{84, 92, 120, 255}}, bar = {{96, 190, 255, 255}};
    if (pass != 2 || !camera || camera->hsd_object != (void *)COBJ_GetCurrent())
        return;
    if (limit[p] >= 1.0f)
    {{
        int beat = glow_tick[p] % 20;
        int k = beat < 10 ? beat : 20 - beat;
        bar.r = 170 + 8 * k;
        bar.g = 225 + 3 * k;
    }}
    a.X = at->X + GAUGE_X - GAUGE_EDGE;
    a.Y = at->Y + GAUGE_Y - GAUGE_EDGE;
    a.Z = at->Z + GAUGE_Z;
    b.X = at->X + GAUGE_X + GAUGE_WIDE + GAUGE_EDGE;
    b.Y = at->Y + GAUGE_Y + GAUGE_TALL + GAUGE_EDGE;
    b.Z = a.Z;
    DRAW_RECT(&a, &b, &edge);
    a.X = at->X + GAUGE_X;
    a.Y = at->Y + GAUGE_Y;
    b.X = a.X + GAUGE_WIDE;
    b.Y = a.Y + GAUGE_TALL;
    DRAW_RECT(&a, &b, &back);
    if (full > 0.0f)
    {{
        b.X = a.X + GAUGE_WIDE * full;
        DRAW_RECT(&a, &b, &bar);
    }}
}}

static void Gauge_Make(int p)
{{
    GOBJ *gobj = GObj_Create(0xE, 0xF, 0);              // the kind of object the game's own displays are
    gobj->userdata = (void *)p;
    GObj_AddGXLink(gobj, Gauge_Draw, HUD_LIST, 1);      // after the display's own pieces
}}

static void OwnLoad(FighterData *fd)
{{
    int i;
    limit[fd->ply] = 0;
    seen_percent[fd->ply] = 0;
    limit_left[fd->ply] = 0;
    boosted[fd->ply] = 0;
    charge_age[fd->ply] = 0;
    charge_armed[fd->ply] = 0;
    was_charging[fd->ply] = 0;
    last_state[fd->ply] = -1;
    for (i = 0; i < 6; i++)
        their_percent[fd->ply][i] = -1.0f;
{boost_keep}    dive_asked[fd->ply] = 0;
    lit[fd->ply] = 0;
    aura[fd->ply] = 0;
    drawn[fd->ply] = 0;
    Gauge_Make(fd->ply);
}}

static void Limit_Draw(GOBJ *gobj, int pass)
{{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    if (drawn[p])
        drawn[p](gobj, pass);
    if (fd->state_id < 12)                                    // nothing while he is gone
        return;
    if (pass == 2 && aura[p])
    {{
        // The aura: thin streaks of light that rise round the fighter and fade as they rise, half of them in
        // front of him and half behind; twice as quick while he charges. (See-through shapes go in the last
        // pass. The routine multiplies a colour by itself, so these are the roots of the colour meant.)
        int i;
        for (i = 0; i < AURA_STREAKS; i++)
        {{
            float t = (float)((glow_tick[p] * aura[p] + i * 11) & 31) / 32.0f;
            GXColor glow = {{196, 234, 255, (u8)(210.0f * (1.0f - t))}};
            Vec3 a, b;
            a.X = fd->phys.pos.X + (float)((i * 37) % 13) - 6.4f;
            b.X = a.X + 0.8f;
            a.Y = fd->phys.pos.Y + t * AURA_TALL;
            b.Y = a.Y + 3.0f + 4.0f * (1.0f - t);
            a.Z = fd->phys.pos.Z + ((i & 1) ? 5.0f : -5.0f);
            b.Z = a.Z;
            DRAW_RECT(&a, &b, &glow);
        }}
    }}
    if (pass == 2 && aura[p] == 2)
    {{
        // While it is being charged the gauge is shown over the fighter as well as by his damage (the game
        // does both): the same bar, just above his head.
        float full = limit[p] >= 1.0f ? 1.0f : limit[p];
        GXColor edge = {{0, 0, 0, 255}}, back = {{84, 92, 120, 255}}, bar = {{96, 190, 255, 255}};
        Vec3 a, b;
        a.X = fd->phys.pos.X - OVER_WIDE * 0.5f - OVER_EDGE;
        a.Y = fd->phys.pos.Y + OVER_Y - OVER_EDGE;
        a.Z = fd->phys.pos.Z + 6.0f;
        b.X = fd->phys.pos.X + OVER_WIDE * 0.5f + OVER_EDGE;
        b.Y = fd->phys.pos.Y + OVER_Y + OVER_TALL + OVER_EDGE;
        b.Z = a.Z;
        DRAW_RECT(&a, &b, &edge);
        a.X += OVER_EDGE;
        a.Y += OVER_EDGE;
        b.X -= OVER_EDGE;
        b.Y -= OVER_EDGE;
        DRAW_RECT(&a, &b, &back);
        if (full > 0.0f)
        {{
            b.X = a.X + OVER_WIDE * full;
            DRAW_RECT(&a, &b, &bar);
        }}
    }}
}}

// The light: the fighter's second colour overlay, which the game draws with when none of its own colour
// animations is running (and which this leaves alone while the game is using it).
static void Limit_Light(FighterData *fd, int p, int charging)
{{
    ColorOverlay *c = &fd->color[1];
    int a = 0;
    aura[p] = limit[p] >= 1.0f ? 1 : charging ? 2 : 0;
    if (c->colanim != 0)
        return;
    if (limit[p] >= 1.0f)
    {{
        int beat = glow_tick[p] % 40;
        a = 40 + 2 * (beat < 20 ? beat : 40 - beat);
    }}
    else if (charging)
        a = 20 + (int)(limit[p] * 40.0f) + ((glow_tick[p] & 7) < 4 ? 15 : 0);
    if (a)
    {{
        // The game keeps the colour twice: as numbers it steps every frame (by "blend" amounts) and as the
        // bytes it draws with, which it writes from the numbers every frame. Setting the bytes alone shows
        // whatever the numbers were left at (a pale grey), so both are set and the steps are zeroed.
        c->color_red = 40.0f;
        c->color_green = 120.0f;
        c->color_blue = 255.0f;
        c->color_alpha = (float)a;
        c->colorblend_red = 0;
        c->colorblend_green = 0;
        c->colorblend_blue = 0;
        c->colorblend_alpha = 0;
        c->hex.r = 40;
        c->hex.g = 120;
        c->hex.b = 255;
        c->hex.a = a;
        c->color_enable = 1;
        lit[p] = 1;
    }}
    else if (lit[p])
    {{
        c->color_enable = 0;
        lit[p] = 0;
    }}
}}

static void Enter(GOBJ *gobj, int state)
{{
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
}}

// Climhazzard, second half: hang for the turn of the sword, then straight down until the ground.
void Dive_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    fd->phys.self_vel.X = 0;
    fd->phys.self_vel.Y = fd->state.frame >= {dive_from}.0f ? -{dive_speed:.3f}f : 0;
}}
static void Dive_Landed(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    Fighter_SetGrounded2(fd);
    Enter(gobj, ST_DIVE_LAND);
}}
void Dive_Coll(GOBJ *gobj)
{{
    Fighter_CollAir_IgnoreLedge(gobj, Dive_Landed);
}}
void DiveLand_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Fighter_EnterWait(gobj);
}}
void Ground_Phys(GOBJ *gobj)
{{
    Fighter_PhysGround_ApplyFriction(gobj);
}}
void Ground_Coll(GOBJ *gobj)
{{
    Fighter_CollGround_StopLedge_EnterFall(gobj);
}}

// Limit Charge: a start, a loop, an end. Once started it goes on by itself until the gauge is full. The special
// button again ends it (not in its first frames: that press started it), and so do shield, a jump, a grab and
// the stick to a side, which go straight to what was asked for where he can do it.
static void Charge_Leave(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_EnterWait(gobj);
    else
        Fighter_EnterFall(gobj);
}}
static void Charge_Count(FighterData *fd)
{{
    int p = fd->ply;
    if (charge_age[p] < 60000)
        charge_age[p]++;
}}
void ChargeStart_IASA(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    float sx = fd->input.lstick.X;
    if (sx < 0.3f && sx > -0.3f)
        charge_armed[fd->ply] = 1;
}}
void ChargeStart_Anim(GOBJ *gobj)
{{
    Charge_Count(gobj->userdata);
    if (FrameTimerCheck(gobj) == 0)
        Enter(gobj, ST_CHARGE_LOOP);
}}
void ChargeLoop_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    Charge_Count(fd);
    limit[p] += LIMIT_PER_FRAME;
    if (limit[p] >= 1.0f)
        Enter(gobj, ST_CHARGE_END);
}}
void ChargeLoop_IASA(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    float sx = fd->input.lstick.X;
    ChargeStart_IASA(gobj);
    if ((fd->input.down & B_BUTTON) && charge_age[p] >= CHARGE_AGAIN)
        Enter(gobj, ST_CHARGE_END);
    else if ((fd->input.down & CANCEL_BUTTONS) || fd->input.lstick.Y > 0.66f
             || (charge_armed[p] && (sx > 0.6f || sx < -0.6f)))
    {{
        int state = fd->state_id;
        if (fd->phys.air_state == 0)
            Fighter_IASACheck_AllGrounded(gobj);
        else
            Fighter_IASACheck_AllAerial(gobj);
        // AllGrounded is ftCo_Wait_IASA (void), despite the old MexTK declaration.
        if (fd->state_id == state)
            Enter(gobj, ST_CHARGE_END);
    }}
    else if (FrameTimerCheck(gobj) == 0)
        Enter(gobj, ST_CHARGE_LOOP);
}}
void ChargeEnd_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Charge_Leave(gobj);
}}
void Charge_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_PhysGround_ApplyFriction(gobj);
    else
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
}}
void Charge_Coll(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_CollGround_StopLedge_EnterFall(gobj);
    else
        Fighter_CollAir_IgnoreLedge(gobj, Fighter_EnterLanding);
}}

// The down special: Finishing Touch (the donor's down special states, which play it) with a full
// gauge, the charge otherwise.
static void DownSpecial(GOBJ *gobj, int finishing)
{{
    FighterData *fd = gobj->userdata;
    if (limit[fd->ply] >= 1.0f)
    {{
        limit[fd->ply] = 0;
        fd->phys.self_vel.Y = 0;
        fd->ftcmd_var.flag1 = 0;                        // the donor's own flag for this state: its window stays shut
        Enter(gobj, finishing);
    }}
    else
    {{
        charge_age[fd->ply] = 0;
        charge_armed[fd->ply] = 0;
        Enter(gobj, ST_CHARGE_START);
    }}
}}
void SpecialLw(GOBJ *gobj)
{{
    DownSpecial(gobj, {finish});
}}
void SpecialAirLw(GOBJ *gobj)
{{
    DownSpecial(gobj, {finish_air});
}}
{limit_code}
static void OwnFrame(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply;
{limit_frame}    // damage taken fills the gauge; taken while he was charging it, it takes that much off it instead
    if (fd->dmg.percent > seen_percent[p])
    {{
        float by = (fd->dmg.percent - seen_percent[p]) * LIMIT_PER_PERCENT;
        if (!was_charging[p])
            limit[p] += by;
        else if (limit[p] < 1.0f)
            limit[p] = limit[p] > by ? limit[p] - by : 0.0f;
    }}
    seen_percent[p] = fd->dmg.percent;
    // the neutral special: as it starts he keeps only part of the speed he had
    if (fd->state_id != last_state[p])
    {{
        if (fd->state_id == N_START)
            fd->phys.self_vel_ground.X *= N_GROUND_X;
        else if (fd->state_id == N_START_AIR)
        {{
            fd->phys.self_vel.X *= N_AIR_X;
            fd->phys.self_vel.Y *= N_AIR_Y;
        }}
    }}
    was_charging[p] = fd->state_id >= ST_CHARGE_START && fd->state_id <= ST_CHARGE_END;
    last_state[p] = fd->state_id;
    // and damage dealt: what another fighter's damage went up by, when this one was the one that hit it
    {{
        int i;
        for (i = 0; i < 6; i++)
        {{
            GOBJ *other = Fighter_GetGObj(i);
            if (other && other != gobj)
            {{
                FighterData *od = other->userdata;
                float was = their_percent[p][i];
                if (was >= 0.0f && od->dmg.percent > was && od->dmg.source_ply == p && limit[p] < 1.0f)
                    limit[p] += (od->dmg.percent - was) * LIMIT_PER_DEALT;
                their_percent[p][i] = od->dmg.percent;
            }}
            else
                their_percent[p][i] = -1.0f;
        }}
    }}
    if (limit[p] >= 1.0f)
    {{
        if (limit[p] != 2.0f)
        {{
            limit_left[p] = LIMIT_HOLD;
{gleam}        }}
        limit[p] = 2.0f;
        // a full gauge left unused runs out
        if (--limit_left[p] <= 0)
            limit[p] = 0;
    }}
    Boost(fd, limit[p] >= 1.0f);
    glow_tick[p]++;
    Limit_Light(fd, p, fd->state_id >= ST_CHARGE_START && fd->state_id <= ST_CHARGE_END);
    if ((void *)gobj->gx_cb != (void *)Limit_Draw)
    {{
        drawn[p] = (void (*)(GOBJ *, int))gobj->gx_cb;
        gobj->gx_cb = (void (*)())Limit_Draw;
    }}
}}
static void OwnInput(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply;
    // the up special: B again once it is rising asks for the dive, which starts where the rise ends
    if (fd->state_id == ST_RISE || fd->state_id == ST_RISE_AIR{rise_more})
    {{
        if (fd->state.frame < 2.0f)
            dive_asked[p] = 0;
        else if (fd->state.frame >= {rise_from}.0f && (fd->input.down & B_BUTTON))
            dive_asked[p] = 1;
        if (dive_asked[p] && fd->state.frame >= {rise_last}.0f)
        {{
            dive_asked[p] = 0;
            Fighter_SetAirborne(fd);
            Enter(gobj, ST_DIVE);
        }}
    }}
}}
'''


# The Limit versions of Cloud's other three specials. The game has a second script for each of their clips
# (found by the driver: `alternates`), which the driver puts on an action of its own beside the plain one.
#   Blade Beam    a faster beam that stops on what it hits, hits five more times and launches (the item's
#                 business; here only which beam is let go)
#   Cross Slash   all of it by itself once the first swing has hit, each swing on the frame the game's
#                 script gives. (The plain one too goes on only once its first swing has hit something:
#                 the driver writes its window on another script flag, and this code passes it on.)
#   Climhazzard   stronger hits and a higher rise (the up special's parameter table has two rows; the one
#                 number that is 1 in the plain row is 1.6 in the Limit row)
CLOUD_LIMIT = '''
// ---- the Limit versions of the other three specials ---------------------------------------------
#define ST_LIMIT_N {n}
#define ST_LIMIT_N_AIR {n_air}
#define ST_LIMIT_S1 {s1}
#define ST_LIMIT_S2 {s2}
#define ST_LIMIT_S3 {s3}
#define ST_LIMIT_S1_AIR {s1_air}
#define ST_LIMIT_S2_AIR {s2_air}
#define ST_LIMIT_S3_AIR {s3_air}
#define ST_LIMIT_RISE {rise}
#define ST_LIMIT_RISE_AIR {rise_air}
#define ST_S1 {plain_s1}
#define ST_S1_AIR {plain_s1_air}
#define LIMIT_RISE {rise_mul:.3f}f              // how much higher the Limit up special goes

static u8 beam_limit[6];            // the neutral special now under way lets the Limit beam go
static u8 slash_hit[6];             // the side special's first swing has hit something
static int seen_state[6];

static void EnterAt(GOBJ *gobj, int state, float rate)
{{
    ActionStateChange(0, rate, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
}}
static void Slash_Hit(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    slash_hit[fd->ply] = 1;
}}

// Limit Cross Slash: once the first swing has hit, the rest follow by themselves
void LimitS1_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (slash_hit[fd->ply] && fd->state.frame >= {s1_next}.0f)
        EnterAt(gobj, fd->phys.air_state == 0 ? ST_LIMIT_S2 : ST_LIMIT_S2_AIR, {s2_rate:.4f}f);
    else if (FrameTimerCheck(gobj) == 0)
        Charge_Leave(gobj);
}}
void LimitS2_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->state.frame >= {s2_next}.0f)
        EnterAt(gobj, fd->phys.air_state == 0 ? ST_LIMIT_S3 : ST_LIMIT_S3_AIR, {s3_rate:.4f}f);
    else if (FrameTimerCheck(gobj) == 0)
        Charge_Leave(gobj);
}}
void LimitEnd_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Charge_Leave(gobj);
}}

// Limit Climhazzard: the donor's own rise, with what its clip gives each frame made that much more
static void Rise_More(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state != 0 && fd->ftcmd_var.flag{rise_flag} && fd->phys.self_vel.Y > 0)
        fd->phys.self_vel.Y *= LIMIT_RISE;
}}
void LimitRise_Phys(GOBJ *gobj)
{{
    ((void (*)(GOBJ *)){rise_phys:#x})(gobj);
    Rise_More(gobj);
}}
void LimitRiseAir_Phys(GOBJ *gobj)
{{
    ((void (*)(GOBJ *)){rise_air_phys:#x})(gobj);
    Rise_More(gobj);
}}

static void LimitFrame(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply, s = fd->state_id;
    int entered = s != seen_state[p] && fd->state.frame < 2.0f;
    if (entered && limit[p] >= 1.0f)
    {{
        // a special started with a full gauge is its Limit version, and the gauge is spent
        int to = 0;
        if ({n_ends})
            to = ST_LIMIT_N;
        else if ({n_air_ends})
            to = ST_LIMIT_N_AIR;
        else if (s == ST_S1)
            to = ST_LIMIT_S1;
        else if (s == ST_S1_AIR)
            to = ST_LIMIT_S1_AIR;
        else if (s == ST_RISE)
            to = ST_LIMIT_RISE;
        else if (s == ST_RISE_AIR)
            to = ST_LIMIT_RISE_AIR;
        if (to)
        {{
            limit[p] = 0;
            if (to == ST_LIMIT_N || to == ST_LIMIT_N_AIR)
                beam_limit[p] = 1;
            EnterAt(gobj, to, (to == ST_LIMIT_S1 || to == ST_LIMIT_S1_AIR) ? {s1_rate:.4f}f : 1.0f);
            s = to;
        }}
    }}
    if (!({n_any}))
        beam_limit[p] = 0;
    if (s == ST_S1 || s == ST_S1_AIR || s == ST_LIMIT_S1 || s == ST_LIMIT_S1_AIR)
    {{
        if (entered)
            slash_hit[p] = 0;
        fd->cb.OnGiveDamage = Slash_Hit;
        fd->cb.OnShieldHit = Slash_Hit;
{gate}    }}
    seen_state[p] = fd->state_id;
}}
'''

BYLETH = '''
// ---- Byleth's own states ---------------------------------------------------------------------
#define ST_LATCH {latch}
#define ST_KICK {kick}
#define ST_WHIP {whip}
#define ST_WHIP_AIR {whip_air}
#define ST_BOW_CANCEL {bow_cancel}
#define ST_AXE_CANCEL {axe_cancel}
#define ST_WALLJUMP {walljump}
#define ST_SIDE {side}
#define SHIELD_BUTTONS 0x60             // R and L
#define BOW_CANCEL_FROM {bow_from}      // the frames of drawing the bow between which it can be put away or left
#define BOW_CANCEL_TO {bow_to}          //   by a jump (the game's own numbers)
#define BOW_TURN_WAIT {bow_turn}        // frames after turning round with the bow drawn before he can again
#define AXE_COMMIT {commit}.0f          // the frame the axe's swing is past stopping (where its armour starts)
#define AXE_TURN_FROM {turn_from}.0f    // the frames between which the axe, drawn, can be turned round (once)
#define AXE_TURN_TO {turn_to}.0f
#define STOMP_DAMAGE {stomp_damage!r}f      // the kick's damage with the whip caught close,
#define STOMP_MORE {stomp_more!r}f        //   times this with it caught at its full reach
#define STOMP_AT {stomp_at!r}f          // the caught fighter's damage from which the kick sends it down:
#define STOMP_ANGLE {stomp_angle}             //   the angle, growth and base of that
#define STOMP_KBG {stomp_kbg}
#define STOMP_BKB {stomp_bkb}
#define WHIP_REACH {whip_reach!r}f        // how far from him the whip's tip gets
#define HOP_X {hop_x!r}f                // the speeds he leaves a kick or a wall with (the game's own numbers)
#define HOP_Y {hop_y!r}f
#define WALL_MAX {wall_max}                  // walls the whip may catch before he lands
#define WALL_FROM {wall_from}.0f           // the frames of the throw on which the whip is out
#define WALL_TO {wall_to}.0f
#define WALL_HAND {wall_hand!r}f          // how high over his feet the whip leaves his hand
#define WALL_ACT {wall_act}.0f           // the frame of the jump off a wall from which he may act
#define WALL_LEFT ((int (*)(float, float, float, float, Vec3 *, int *, u32 *, Vec3 *, int, int))0x800501CC)    // mpCheckLeftWall
#define WALL_RIGHT ((int (*)(float, float, float, float, Vec3 *, int *, u32 *, Vec3 *, int, int))0x800509B8)   // mpCheckRightWall
#define LUNGE_SPEED {lunge_speed!r}f      // the side special asked for with a flick: the speed forward it starts with,
#define LUNGE_BRAKE {lunge_brake!r}f      //   and what comes off that each frame
#define LUNGE_FLICK {lunge_flick}               // frames since the stick was flicked that still count
#define WHIP_START_Y {whip_start_y:.4f}f  // the speed upward the air up special starts with (the game's own number)
#define TIP_JOINT {tip}                 // the whip's last joint
#define LATCH_ABOVE {above:.3f}f        // how far above the caught fighter's feet his own end up, so the kick is on them

static Vec3 latch_at[6];                // where each player's whip caught something,
static s8 latch_on[6];                  // and which player it caught (-1: none, only a place)
static u8 latched[6];
static u8 axe_turned[6];                // the axe has been turned round in this swing
static u8 whip_started[6];              // the air up special now under way has been given its starting speed
static u16 bow_age[6];                  // frames the bow has been out
static u8 bow_wait[6];                  // frames until he can turn round with it again
static u8 wall_count[6];                // walls the whip has caught since he last stood
static u8 on_wall[6];                   // what the whip caught this time is a wall
static float wall_away[6];              // which way is off that wall
static float stomp[6];                  // how many times its damage the kick now coming does
static float lunge[6];                  // the speed forward the side special still has from its flick
static int last_state[6];

static void OwnLoad(FighterData *fd)
{{
    latched[fd->ply] = 0;
    axe_turned[fd->ply] = 0;
    latch_on[fd->ply] = -1;
    bow_age[fd->ply] = 0;
    bow_wait[fd->ply] = 0;
    wall_count[fd->ply] = 0;
    on_wall[fd->ply] = 0;
    stomp[fd->ply] = 1.0f;
    lunge[fd->ply] = 0;
    last_state[fd->ply] = -1;
}}

static void Turn_Round(FighterData *fd)
{{
    fd->facing_direction = -fd->facing_direction;
    Fighter_SetBoneRotY(fd, 0, 1.5707963f * fd->facing_direction);
}}

static void Enter(GOBJ *gobj, int state)
{{
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
}}

// the whip has hit something: remember where the fighter it caught is (the nearest other one; failing
// that, where the whip's tip is)
static void Whip_Hit(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    float best = 1.0e12f;
    int i;
    JOBJ_GetWorldPosition(fd->bones[TIP_JOINT].joint, 0, &latch_at[fd->ply]);
    latch_on[fd->ply] = -1;
    on_wall[fd->ply] = 0;
    stomp[fd->ply] = 1.0f;
    for (i = 0; i < 6; i++)
    {{
        GOBJ *other = Fighter_GetGObj(i);
        if (other && other != gobj)
        {{
            FighterData *od = other->userdata;
            float dx = od->phys.pos.X - fd->phys.pos.X, dy = od->phys.pos.Y - fd->phys.pos.Y;
            if (dx * dx + dy * dy < best)
            {{
                best = dx * dx + dy * dy;
                latch_on[fd->ply] = i;
                latch_at[fd->ply] = od->phys.pos;
                latch_at[fd->ply].Y += LATCH_ABOVE;
            }}
        }}
    }}
    if (latch_on[fd->ply] >= 0)
    {{
        // the further off the caught fighter was, the harder the kick (up to STOMP_MORE times at the whip's
        // full reach). (The whip is at its full length within a frame or two, so where its tip is says nothing.)
        float far = sqrtf(best) / WHIP_REACH;
        stomp[fd->ply] = 1.0f + (STOMP_MORE - 1.0f) * (far > 1.0f ? 1.0f : far);
    }}
    latched[fd->ply] = 1;
}}

// the catch: drawn to what was caught (wherever the hit has since sent it), to arrive as the clip ends
void Latch_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    Vec3 *to = &latch_at[fd->ply];
    float left = {latch_frames}.0f - fd->state.frame;
    if (latch_on[fd->ply] >= 0)
    {{
        GOBJ *other = Fighter_GetGObj(latch_on[fd->ply]);
        if (other)
        {{
            FighterData *od = other->userdata;
            *to = od->phys.pos;
            to->Y += LATCH_ABOVE;
        }}
    }}
    if (left < 1.0f)
        left = 1.0f;
    fd->phys.self_vel.X = (to->X - fd->phys.pos.X) / left;
    fd->phys.self_vel.Y = (to->Y - fd->phys.pos.Y) / left;
}}
void Latch_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (FrameTimerCheck(gobj) != 0)
        return;
    if (on_wall[fd->ply])
    {{
        // at the wall: he jumps off it, facing away
        float away = wall_away[fd->ply];
        on_wall[fd->ply] = 0;
        if (fd->facing_direction != away)
            Turn_Round(fd);
        Enter(gobj, ST_WALLJUMP);
        fd->phys.self_vel.X = HOP_X * away;
        fd->phys.self_vel.Y = HOP_Y;
    }}
    else
        Enter(gobj, ST_KICK);
}}
void WallJump_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->state.frame >= WALL_ACT || FrameTimerCheck(gobj) == 0)
        Fighter_EnterFall(gobj);
}}
void WallJump_Phys(GOBJ *gobj)
{{
    Fighter_PhysAir_ApplyGravityFastfall(gobj);
}}
void Own_AirColl(GOBJ *gobj)
{{
    Fighter_CollAir_IgnoreLedge(gobj, Fighter_EnterLanding);
}}

// the kick: he hangs there for it, then hops off and can act
// (The kick's hit is made by its script, after this code's per-frame work and before anything is struck: its
// numbers are set here, in the state's own step between the two. The game has three kicks and picks one by the
// caught fighter's damage; the script here holds the one that sends it up.)
void Kick_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    int p = fd->ply, i, down = 0;
    fd->phys.self_vel.X = 0;
    fd->phys.self_vel.Y = 0;
    if (latch_on[p] >= 0)
    {{
        GOBJ *other = Fighter_GetGObj(latch_on[p]);
        if (other)
            down = ((FighterData *)other->userdata)->dmg.percent >= STOMP_AT;
    }}
    for (i = 0; i < 4; i++)
    {{
        ftHit *hit = &fd->hitbox[i];
        if (!hit->active)
            continue;
        Fighter_UpdateHitboxDamage(hit, (int)(STOMP_DAMAGE * stomp[p] + 0.5f), gobj);
        if (down)
        {{
            hit->angle = STOMP_ANGLE;
            hit->kb_growth = STOMP_KBG;
            hit->kb = STOMP_BKB;
        }}
    }}
}}
void Kick_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (FrameTimerCheck(gobj) == 0)
    {{
        Fighter_EnterFall(gobj);
        fd->phys.self_vel.X = HOP_X * fd->input.lstick.X;
        fd->phys.self_vel.Y = HOP_Y;
    }}
}}

// putting a weapon away: the clip, then free
void Cancel_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (FrameTimerCheck(gobj) == 0)
    {{
        if (fd->phys.air_state == 0)
            Fighter_EnterWait(gobj);
        else
            Fighter_EnterFall(gobj);
    }}
}}
void Cancel_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_PhysGround_ApplyFriction(gobj);
    else
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
}}
void Cancel_Coll(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_CollGround_StopLedge_EnterFall(gobj);
    else
        Fighter_CollAir_IgnoreLedge(gobj, Fighter_EnterLanding);
}}

static void OwnInput(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply, s = fd->state_id;
    // the bow: between two frames of drawing it shield puts it away and a jump leaves it; once it is drawn,
    // the stick held the other way turns him round
    if ({bow_states})
    {{
        if (bow_age[p] >= BOW_CANCEL_FROM && bow_age[p] <= BOW_CANCEL_TO)
        {{
            if (fd->input.down & SHIELD_BUTTONS)
            {{
                Enter(gobj, ST_BOW_CANCEL);
                return;
            }}
            if (fd->phys.air_state == 0 ? Fighter_IASACheck_JumpF(gobj) : Fighter_IASACheck_JumpAerial(gobj))
                return;
        }}
        if (({bow_held}) && !bow_wait[p] && fd->input.lstick.X * fd->facing_direction < -0.5f)
        {{
            bow_wait[p] = BOW_TURN_WAIT;
            Turn_Round(fd);
        }}
    }}
    // the axe: shield puts it away before its swing is past stopping; held back, it can be turned round once,
    // the stick the other way. (The game does this in its code, not in the move's script: the frames are the
    // published ones.)
    if ({axe_states})
    {{
        if ((fd->input.down & SHIELD_BUTTONS) && fd->state.frame < AXE_COMMIT)
        {{
            Enter(gobj, ST_AXE_CANCEL);
            return;
        }}
        if (!axe_turned[p] && fd->state.frame >= AXE_TURN_FROM && fd->state.frame <= AXE_TURN_TO
            && fd->input.lstick.X * fd->facing_direction < -0.5f)
        {{
            axe_turned[p] = 1;
            Turn_Round(fd);
        }}
    }}
}}

static void OwnFrame(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply, s = fd->state_id, was = last_state[p];
    last_state[p] = s;
    if (fd->phys.air_state == 0)
        wall_count[p] = 0;                              // the whip may catch walls again once he has stood
    if ({bow_states})
    {{
        if (bow_age[p] < 60000)
            bow_age[p]++;
        if (bow_wait[p])
            bow_wait[p]--;
    }}
    else
    {{
        bow_age[p] = 0;
        bow_wait[p] = 0;
    }}
    if (({axe_states}) && fd->state.frame < 2.0f)
        axe_turned[p] = 0;
    // the side special on the ground, asked for with a flick of the stick: he dashes forward as it starts
    if (s == ST_SIDE)
    {{
        if (s != was)
            lunge[p] = fd->input.timer_lstick_smash_x < LUNGE_FLICK ? LUNGE_SPEED : 0.0f;
        if (lunge[p] > 0.0f && fd->phys.air_state == 0)
        {{
            fd->phys.self_vel_ground.X = (lunge[p] + fd->attr.ground_friction) * fd->facing_direction;
            lunge[p] -= LUNGE_BRAKE;
        }}
    }}
    else
        lunge[p] = 0;
    if (fd->state_id != ST_WHIP && fd->state_id != ST_WHIP_AIR)
    {{
        whip_started[p] = 0;
        return;
    }}
    // thrown in the air, the whip starts with a speed upward of the fighter's own (the game sets it as the
    // special starts: without it the fighter falls all through the throw, out of the whip's reach of a ledge)
    if (fd->state_id == ST_WHIP_AIR && !whip_started[p])
    {{
        whip_started[p] = 1;
        fd->phys.self_vel.Y = WHIP_START_Y;
    }}
    if (fd->state.frame < 2.0f)
        latched[p] = 0;
    fd->cb.OnGiveDamage = Whip_Hit;
    if (latched[p])
    {{
        latched[p] = 0;
        if (fd->phys.air_state == 0)
            Fighter_SetAirborne(fd);
        Enter(gobj, ST_LATCH);
    }}
    else if (fd->state_id == ST_WHIP_AIR && wall_count[p] < WALL_MAX
             && fd->state.frame >= WALL_FROM && fd->state.frame <= WALL_TO)
    {{
        // the whip's tip has gone into a wall: he is drawn to where it struck and jumps off (the game's code
        // does this; a wall is looked for along the line from his hand to the tip)
        Vec3 tip, hit, normal;
        int line;
        u32 flags;
        float ax = fd->phys.pos.X, ay = fd->phys.pos.Y + WALL_HAND;
        JOBJ_GetWorldPosition(fd->bones[TIP_JOINT].joint, 0, &tip);
        if (WALL_LEFT(ax, ay, tip.X, tip.Y, &hit, &line, &flags, &normal, -1, -1)
            || WALL_RIGHT(ax, ay, tip.X, tip.Y, &hit, &line, &flags, &normal, -1, -1))
        {{
            wall_away[p] = hit.X < ax ? 1.0f : -1.0f;
            latch_at[p].X = hit.X + wall_away[p] * 3.0f;
            latch_at[p].Y = hit.Y - WALL_HAND;
            latch_at[p].Z = fd->phys.pos.Z;
            latch_on[p] = -1;
            on_wall[p] = 1;
            wall_count[p]++;
            Enter(gobj, ST_LATCH);
        }}
    }}
}}
'''


def master(ctx):
    action, total = ctx['action'], ctx['total']
    need = ('SpecialAirS4Hi', 'SpecialAirS4Lw', 'SpecialHi', 'SpecialAirHi', 'SpecialS2Hi', 'SpecialS2Lw')
    missing = [m for m in need if m not in action or not total.get(m)]
    if missing or ctx.get('tip') is None:
        return None, f'no clips on {missing}' if missing else 'no whip to latch with'
    first, air = ctx['first'], ctx['flags']['air']
    own, tether = ctx.get('own') or {}, ctx.get('tether')
    hi, side, bow = own.get('hi') or {}, own.get('s') or {}, own.get('n') or {}
    world = float(ctx['world'])
    # the wall: only with the clip of the jump off it carried and the whip's reach known
    wall = bool(action.get('SpecialAirS4S') is not None and total.get('SpecialAirS4S') and tether and hi.get('wall_hit_max'))
    stomp = ctx.get('stomp') or {}
    rows = [
        {'name': 'the whip has caught something', 'action': action['SpecialAirS4Hi'], 'flags': air, 'move': ctx['move']['up'],
         'anim': 'Latch_Anim', 'phys': 'Latch_Phys', 'coll': 'Own_AirColl'},
        {'name': 'the kick off it', 'action': action['SpecialAirS4Lw'], 'flags': air, 'move': ctx['move']['up'],
         'anim': 'Kick_Anim', 'phys': 'Kick_Phys', 'coll': 'Own_AirColl'},
        {'name': 'the bow put away', 'action': action['SpecialS2Hi'], 'flags': ctx['flags']['ground'], 'move': ctx['move']['down'],
         'anim': 'Cancel_Anim', 'phys': 'Cancel_Phys', 'coll': 'Cancel_Coll'},
        {'name': 'the axe put away', 'action': action['SpecialS2Lw'], 'flags': ctx['flags']['ground'], 'move': ctx['move']['down'],
         'anim': 'Cancel_Anim', 'phys': 'Cancel_Phys', 'coll': 'Cancel_Coll'},
    ]
    if wall:
        rows.append({'name': 'the jump off a wall the whip caught', 'action': action['SpecialAirS4S'], 'flags': air,
                     'move': ctx['move']['up'], 'anim': 'WallJump_Anim', 'phys': 'WallJump_Phys', 'coll': 'Own_AirColl'})
    st = ctx['state']
    is_in = lambda names: ' || '.join(f's == {st[n]}' for n in names if n in st) or '0'
    # the whip leaves his hand a little over half his height up; its reach is from there to where its tip gets
    hand = 0.6 * float(ctx.get('head') or 16.0 * world)
    reach = (float(tether['width']) ** 2 + (float(tether['height']) - hand) ** 2) ** 0.5 if tether else 40.0 * world
    source = BYLETH.format(latch=first, kick=first + 1, bow_cancel=first + 2, axe_cancel=first + 3,
                           walljump=first + 4 if wall else first + 1,
                           side=st.get('SpecialS1', -1),
                           bow_states=is_in(('SpecialNStart', 'SpecialNLoop', 'SpecialAirNStart', 'SpecialAirNLoop')),
                           bow_held=is_in(('SpecialNLoop', 'SpecialAirNLoop')),
                           axe_states=is_in(('SpecialLw', 'SpecialAirLw')),
                           # the bow: the frames it can be put away between, and the wait between turns (the file's own, by name)
                           bow_from=int(bow.get('cancel_start_frame') or 1), bow_to=int(bow.get('cancel_end_frame') or 60000),
                           bow_turn=int(bow.get('turn_disable_frame') or 0),
                           commit=int(ctx.get('commit') or 40),     # where the game's armour starts; 40 when that is not known
                           turn_from=12, turn_to=41,                # published: the frames the axe can be turned round on
                           # the kick: its damage and the numbers of the one that sends a fighter down (the script's own);
                           # from what damage, and how much harder at full reach (the file's, under names that do not resolve)
                           stomp_damage=float(stomp.get('damage') or 6.5), stomp_angle=int(stomp.get('angle') or 260),
                           stomp_kbg=int(stomp.get('kbg') or 110), stomp_bkb=int(stomp.get('bkb') or 14),
                           stomp_at=float(hi.get('0x16ac56872a') or 50.0), stomp_more=float(hi.get('0x171e7b6a7c') or 2.0),
                           whip_reach=reach,
                           hop_x=float(hi.get('jump_speed_x') or 0.9) * world, hop_y=float(hi.get('jump_speed_y') or 2.6) * world,
                           wall_max=int(hi.get('wall_hit_max') or 0) if wall else 0,
                           # (a ledge in the whip's reach is caught first: the engine's own catch gets two frames' start)
                           wall_from=int(tether['first']) + 2 if tether else 0, wall_to=int(tether['last']) if tether else 0,
                           wall_hand=hand,
                           wall_act=max(2, int(ctx.get('wall_act') or 24) - 1),
                           # the dash of a flicked side special (two of the file's values whose names do not resolve,
                           # read as a speed and what comes off it each frame)
                           lunge_speed=float(side.get('0x0c7cbfe735') or 0.0) * world, lunge_brake=float(side.get('0x0ce4436a80') or 1.0) * world,
                           lunge_flick=6,
                           whip_start_y=float((ctx.get('start_y') or {}).get('hi') or 0.0),
                           whip=ctx['state']['SpecialHi'], whip_air=ctx['state']['SpecialAirHi'],
                           tip=int(ctx['tip']), above=3.0 * ctx['world'],      # a little off the ground (not in the game's files: the kick is a throw there)
                           latch_frames=int(total['SpecialAirS4Hi']))
    wrappers, iasa = _input_wrappers(ctx, ('SpecialNStart', 'SpecialNLoop', 'SpecialAirNStart',
                                          'SpecialAirNLoop', 'SpecialLw', 'SpecialAirLw'), 'OwnInput')
    source += '\n' + wrappers
    return {'source': source.strip('\n').split('\n'), 'rows': rows, 'donor_iasa': iasa,
            'load': ['OwnLoad(fd);'], 'frame': ['OwnFrame(fd, gobj);'],
            'provides': ['the whip latches onto what it hits: a pull to it, a kick, a hop',
                         'the kick sends a hurt fighter down, and is harder the further out the whip caught it',
                         'shield puts the bow away, and the axe before it swings; a jump leaves the bow',
                         'the bow, drawn, can be turned round; the axe once before it swings',
                         'a flicked side special dashes forward']
                        + (['the whip catches walls: a pull to the wall and a jump off it'] if wall else [])}, None


# Where the Limit gauge sits on a player's damage display, in the display's own units from the display's own
# point (the foot of the number's last digit; a digit is about 3 wide and 4 tall, the stock icons sit from 6
# up): its left end and lower edge, its size, how far toward the camera, and the width of its dark edge.
# It lies over the number and under the stock icons, as wide as a two-digit number and its percent sign.
GAUGE = {'x': -2.4, 'y': 4.7, 'wide': 8.0, 'tall': 0.6, 'z': 0.0, 'edge': 0.14}


def cloud(ctx):
    first, action, total = ctx['first'], ctx['action'], ctx['total']
    need = ('SpecialAirS4Hi', 'SpecialS4Hi', 'SpecialS4S', 'SpecialS4Lw', 'SpecialAirS4S', 'SpecialHi')
    missing = [m for m in need if m not in action or not total.get(m)]
    if missing:
        return None, f'no clips on {missing}'
    air, ground = ctx['flags']['air'], ctx['flags']['ground']
    rows = [
        {'name': 'the dive', 'action': action['SpecialAirS4Hi'], 'flags': air, 'move': ctx['move']['up'],
         'phys': 'Dive_Phys', 'coll': 'Dive_Coll'},
        {'name': 'its landing', 'action': action['SpecialS4Hi'], 'flags': ground, 'move': ctx['move']['up'],
         'anim': 'DiveLand_Anim', 'phys': 'Ground_Phys', 'coll': 'Ground_Coll'},
        {'name': 'Limit Charge starts', 'action': action['SpecialS4S'], 'flags': ground, 'move': ctx['move']['down'],
         'anim': 'ChargeStart_Anim', 'iasa': 'ChargeStart_IASA', 'phys': 'Charge_Phys', 'coll': 'Charge_Coll'},
        {'name': 'Limit Charge', 'action': action['SpecialS4Lw'], 'flags': ground, 'move': ctx['move']['down'],
         'anim': 'ChargeLoop_Anim', 'iasa': 'ChargeLoop_IASA', 'phys': 'Charge_Phys', 'coll': 'Charge_Coll'},
        {'name': 'Limit Charge ends', 'action': action['SpecialAirS4S'], 'flags': ground, 'move': ctx['move']['down'],
         'anim': 'ChargeEnd_Anim', 'phys': 'Charge_Phys', 'coll': 'Charge_Coll'},
    ]
    hits = [h['first'] for h in (ctx['moves'].get('game_specialhi2') or {}).get('hitboxes', []) if isinstance(h.get('first'), int)]
    # the Limit versions of the other specials, when the driver found the game's second scripts for them
    alt, row, st = ctx.get('alt') or {}, ctx.get('row') or {}, ctx['state']
    limit_names = ('SpecialNEnd', 'SpecialAirNEnd', 'SpecialS1', 'SpecialS2Hi', 'SpecialS3Hi',
                   'SpecialAirS1', 'SpecialAirS2Hi', 'SpecialAirS3Hi', 'SpecialHi', 'SpecialAirHi')
    limit_code, limit_frame, rise_more, entries, provides = '', '', '', [first + 2], []
    shot = None
    if all(m in alt and m in row for m in limit_names) and all(k in ctx for k in ('alt_rate', 'alt_next', 'n_states')):
        base = first + len(rows)
        own = lambda name, m, **calls: dict({'name': name, 'action': alt[m], 'flags': row[m]['flags'], 'move': row[m]['move'],
                                             'bits': row[m]['bits'], 'camera': row[m]['camera']}, **calls)
        donor = lambda name, m: own(name, m, anim=row[m]['anim'], iasa=row[m]['iasa'], phys=row[m]['phys'], coll=row[m]['coll'])
        slash = lambda name, m, anim: own(name, m, anim=anim, phys=row[m]['phys'], coll='Charge_Coll')
        rows += [
            donor('Limit Blade Beam', 'SpecialNEnd'), donor('Limit Blade Beam in the air', 'SpecialAirNEnd'),
            slash('Limit Cross Slash, first swing', 'SpecialS1', 'LimitS1_Anim'),
            slash('Limit Cross Slash, second', 'SpecialS2Hi', 'LimitS2_Anim'),
            slash('Limit Cross Slash, the rest', 'SpecialS3Hi', 'LimitEnd_Anim'),
            slash('Limit Cross Slash in the air, first swing', 'SpecialAirS1', 'LimitS1_Anim'),
            slash('Limit Cross Slash in the air, second', 'SpecialAirS2Hi', 'LimitS2_Anim'),
            slash('Limit Cross Slash in the air, the rest', 'SpecialAirS3Hi', 'LimitEnd_Anim'),
            dict(donor('Limit Climhazzard', 'SpecialHi'), phys='LimitRise_Phys'),
            dict(donor('Limit Climhazzard in the air', 'SpecialAirHi'), phys='LimitRiseAir_Phys'),
        ]
        n = ctx['n_states']                             # the donor states the neutral special is in, start to end
        is_in = lambda states: ' || '.join(f's == {int(x)}' for x in states)
        gate = ctx.get('gate')
        limit_code = CLOUD_LIMIT.format(
            n=base, n_air=base + 1, s1=base + 2, s2=base + 3, s3=base + 4, s1_air=base + 5, s2_air=base + 6, s3_air=base + 7,
            rise=base + 8, rise_air=base + 9, plain_s1=st['SpecialS1'], plain_s1_air=st['SpecialAirS1'],
            rise_mul=float(ctx.get('rise_mul') or 1.0), rise_flag=int(ctx.get('rise_flag') or 0),
            rise_phys=int(row['SpecialHi']['phys']), rise_air_phys=int(row['SpecialAirHi']['phys']),
            s1_next=int(ctx['alt_next']['SpecialS1']), s2_next=int(ctx['alt_next']['SpecialS2Hi']),
            s1_rate=float(ctx['alt_rate']['SpecialS1']), s2_rate=float(ctx['alt_rate']['SpecialS2Hi']),
            s3_rate=float(ctx['alt_rate']['SpecialS3Hi']),
            n_ends=is_in(n['ends']), n_air_ends=is_in(n['air_ends']),
            n_any=is_in(list(n['all']) + [base, base + 1]),
            gate=('        // the plain one goes on only once its first swing has hit: its window is passed on then\n'
                  '        if (s == ST_S1 || s == ST_S1_AIR)\n'
                  f'            fd->ftcmd_var.flag0 = (fd->ftcmd_var.flag{int(gate)} && slash_hit[p]) ? 1 : 0;\n') if gate else '')
        limit_frame = '    LimitFrame(fd, gobj);\n'
        rise_more = ' || fd->state_id == ST_LIMIT_RISE || fd->state_id == ST_LIMIT_RISE_AIR'
        entries += [base + 2, base + 5, base + 8, base + 9]
        provides = ['the Limit versions of the other three specials, picked while the gauge is full',
                    'Cross Slash goes on only once its first swing has hit']
        shot = {'variant': 'beam_limit[fd->ply]', 'states': {'ground': [base] + list(n['ends']), 'air': [base + 1] + list(n['air_ends'])}}
    # the fighter's numbers a full gauge changes: {MexTK field: times}
    boost = [(f, float(m)) for f, m in sorted((ctx.get('boost') or {}).items())]
    boost_store = f'static float plain[6][{max(1, len(boost))}];   // the fighter\'s own numbers, kept from when it loaded'
    boost_keep = ''.join(f'    plain[fd->ply][{i}] = fd->attr.{f};\n' for i, (f, _) in enumerate(boost))
    boost_apply = ''.join(f'    fd->attr.{f} = plain[p][{i}] * (on ? {m!r}f : 1.0f);\n' for i, (f, m) in enumerate(boost))
    own_n = (ctx.get('own') or {}).get('n') or {}
    gleam = ''
    if ctx.get('gleam'):
        # full: a gleam on the sword says so (Melee's own, the one a smash attack being charged has)
        gleam = ('            Vec3 none = {0, 0, 0};\n'
                 f"            SPAWN_EFFECT(gobj, {int(ctx['gleam']['gfx'])}, {int(ctx['gleam']['bone'])}, 0, 0, &none, &none, 0.0f);\n")
    source = CLOUD.format(
        limit_code=limit_code, limit_frame=limit_frame, rise_more=rise_more,
        dive=first, dive_land=first + 1, charge_start=first + 2, charge_loop=first + 3, charge_end=first + 4,
        rise=ctx['state']['SpecialHi'], rise_air=ctx['state']['SpecialAirHi'],
        # the gauge: frames of charging, damage taken and damage dealt that fill it (the move's published data: the
        # game's file holds them under names that do not resolve), and how long a full one lasts (the file's own)
        charge_frames=334, charge_damage=100, charge_dealt=150, limit_hold=int(ctx.get('limit_hold') or 900),
        charge_again=8,                                 # published: the button cannot end it in its first 8 frames
        # the neutral special: what he keeps of his speed as it starts (the file's own, by name)
        n_start=ctx['state'].get('SpecialNStart', -1), n_start_air=ctx['state'].get('SpecialAirNStart', -1),
        n_ground_x=float(own_n.get('speed_x_mul', 1.0)), n_air_x=float(own_n.get('air_speed_x_mul', 1.0)),
        n_air_y=float(own_n.get('air_speed_y_mul', 1.0)),
        boost_store=boost_store, boost_apply=boost_apply, boost_keep=boost_keep,
        # the bar on the damage display, in the display's own units (placed by eye against the damage number)
        gauge_x=GAUGE['x'], gauge_y=GAUGE['y'], gauge_wide=GAUGE['wide'], gauge_tall=GAUGE['tall'], gauge_z=GAUGE['z'],
        gauge_edge=GAUGE['edge'],
        aura_tall=float(ctx.get('head') or 20.0) + 3.0,
        gleam=gleam,
        dive_from=min(hits) if hits else 12,            # the script's hitboxes come out as the plunge starts
        dive_speed=7.0 * ctx['world'],                  # the first value of the up special's parameter table (its name does not resolve)
        rise_from=ctx.get('rise') or 8, rise_last=int(total['SpecialHi']) - 1,
        finish=ctx['state']['SpecialLw'], finish_air=ctx['state']['SpecialAirLw'])
    wrappers, iasa = _input_wrappers(ctx, ('SpecialHi', 'SpecialAirHi'), 'OwnInput',
                                    [r for r in rows if r['name'].startswith('Limit Climhazzard')])
    source += '\n' + wrappers
    return {'source': source.strip('\n').split('\n'), 'rows': rows, 'donor_iasa': iasa,
            'load': ['OwnLoad(fd);'], 'frame': ['OwnFrame(fd, gobj);'],
            'entries': entries, 'shot': shot,
            'provides': ["Climhazzard's dive", 'the Limit gauge: charge, and Finishing Touch when it is full',
                         'Limit Charge goes on by itself and is ended by the button, shield, a jump, a grab or the stick',
                         'a hit taken while charging takes from the gauge'] + provides}, None


IKE = '''
// ---- Ike's own states --------------------------------------------------------------------------
#define ST_QD {qd}                      // Quick Draw: start, hold, dash, swing, end; then the same five in the air
#define ST_PLUNGE {plunge}
#define ST_SLAM {slam}
#define ST_SIDE {side}                  // the donor's states the side and up specials start in
#define ST_SIDE_AIR {side_air}
#define ST_UP {up}
#define ST_UP_AIR {up_air}
#define B_BUTTON 0x200
#define QD_MAX {qd_max}                 // frames of holding that still add to it
#define QD_SPEED {qd_speed!r}f          // the dash's speed with no charge, on the ground and in the air,
#define QD_SPEED_AIR {qd_speed_air!r}f
#define QD_GAIN {qd_gain!r}f            //   and what each frame of charge adds to it
#define QD_GAIN_AIR {qd_gain_air!r}f
#define QD_DAMAGE {qd_damage!r}f        // the swing's damage with no charge, and what each frame of charge adds
#define QD_DAMAGE_GAIN {qd_damage_gain!r}f
#define QD_REACH {qd_reach!r}f          // how near ahead a fighter must be for him to swing, and how far above or below
#define QD_TALL {qd_tall!r}f
#define QD_SWING_SPEED {qd_swing_speed!r}f  // the speed forward the swing starts with (its script's own)
#define QD_END {qd_end!r}f                 // the end: what is left of the dash's speed as it begins, and what each
#define QD_BRAKE {qd_brake!r}f             //   frame then takes off it, on the ground and in the air
#define QD_BRAKE_AIR {qd_brake_air!r}f
#define PLUNGE_SPEED {plunge_speed!r}f  // the speed he comes down at (the plunge's script's own)
#define UP_LAST {up_last}.0f            // the last frame of the rise
#define FALL_LAG {fall_lag}.0f          // frames of landing after a special that leaves him helpless
#define RECOIL {recoil!r}f              // what a full charge of the neutral special costs him
#define LEDGE_CHECK ((void *)0x80096CC8)    // what the donor's own up special looks for a ledge with (ftCo_80096CC8)

static u8 qd_charge[6];
static int last_state[6];

static void OwnLoad(FighterData *fd)
{{
    qd_charge[fd->ply] = 0;
    last_state[fd->ply] = -1;
}}
static void Enter(GOBJ *gobj, int state)
{{
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
}}
static int Qd(FighterData *fd, int step)
{{
    return ST_QD + step + (fd->phys.air_state == 0 ? 0 : 5);
}}
static float Qd_Speed(FighterData *fd)
{{
    float c = (float)qd_charge[fd->ply];
    return fd->phys.air_state == 0 ? QD_SPEED + QD_GAIN * c : QD_SPEED_AIR + QD_GAIN_AIR * c;
}}
// out of a special: standing, or (in the air) falling helpless, as the game leaves him
static void Leave(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_EnterWait(gobj);
    else
        Fighter_EnterSpecialFall(gobj, 1, 0, 1, 1.0f, FALL_LAG);
}}

// Quick Draw. Where he stands he slows; in the air he falls while he crouches and charges.
void Qd_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_PhysGround_ApplyFriction(gobj);
    else
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
}}
void Qd_Coll(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_CollGround_StopLedge_EnterFall(gobj);
    else
        Fighter_CollAir_IgnoreLedge(gobj, Fighter_EnterLanding);
}}
void QdStart_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Enter(gobj, Qd(gobj->userdata, 1));
}}
// held as long as the button is: the charge grows to its most and stays there
void QdHold_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (qd_charge[fd->ply] < QD_MAX)
        qd_charge[fd->ply]++;
}}
void QdHold_IASA(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (!(fd->input.held & B_BUTTON))
        Enter(gobj, Qd(fd, 2));
    else if (FrameTimerCheck(gobj) == 0)
        Enter(gobj, Qd(fd, 1));
}}
// the dash: straight ahead at the speed the charge gives; on the ground he stops at an edge
void QdDash_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    float v = Qd_Speed(fd) * fd->facing_direction;
    if (fd->phys.air_state == 0)
    {{
        fd->phys.self_vel_ground.X = v + fd->attr.ground_friction * fd->facing_direction;
        Fighter_PhysGround_ApplyFriction(gobj);
    }}
    else
    {{
        fd->phys.self_vel.X = v;
        fd->phys.self_vel.Y = 0;
    }}
}}
void QdDash_Coll(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_CollGround_StopLedge_EnterFall(gobj);
    else
        Fighter_CollAir_GrabFacingLedgeWalljump(gobj, LEDGE_CHECK, Fighter_EnterLanding);
}}
// he swings at the first fighter he reaches; with no one in his way the dash runs out
void QdDash_Anim(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    float reach = QD_REACH + Qd_Speed(fd);
    int i;
    for (i = 0; i < 6; i++)
    {{
        GOBJ *other = Fighter_GetGObj(i);
        if (other && other != gobj)
        {{
            FighterData *od = other->userdata;
            float dx = (od->phys.pos.X - fd->phys.pos.X) * fd->facing_direction;
            float dy = od->phys.pos.Y - fd->phys.pos.Y;
            if (dx > -2.0f && dx < reach && dy > -QD_TALL && dy < QD_TALL)
            {{
                Enter(gobj, Qd(fd, 3));
                if (fd->phys.air_state == 0)
                    fd->phys.self_vel_ground.X = QD_SWING_SPEED * fd->facing_direction;
                else
                    fd->phys.self_vel.X = QD_SWING_SPEED * fd->facing_direction;
                return;
            }}
        }}
    }}
    if (FrameTimerCheck(gobj) == 0)
    {{
        Enter(gobj, Qd(fd, 4));
        if (fd->phys.air_state == 0)
            fd->phys.self_vel_ground.X = Qd_Speed(fd) * fd->facing_direction * QD_END;
        else
            fd->phys.self_vel.X = Qd_Speed(fd) * fd->facing_direction * QD_END;
    }}
}}
// the swing: its script makes the hit, and the charge sets the hit's damage here (after the script has made it
// and before it strikes anything)
void QdSwing_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    int i, damage = (int)(QD_DAMAGE + QD_DAMAGE_GAIN * (float)qd_charge[fd->ply] + 0.5f);
    Qd_Phys(gobj);
    for (i = 0; i < 4; i++)
        if (fd->hitbox[i].active)
            Fighter_UpdateHitboxDamage(&fd->hitbox[i], damage, gobj);
}}
// the end: he keeps part of the dash's speed and is braked to a stop (in the air he falls as he is braked)
static void Qd_Brake(float *v, float by)
{{
    if (*v > by)
        *v -= by;
    else if (*v < -by)
        *v += by;
    else
        *v = 0;
}}
void QdEnd_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {{
        // (the game's friction step is what turns ground speed into movement: the brake is that friction and the rest)
        Qd_Brake(&fd->phys.self_vel_ground.X, QD_BRAKE - fd->attr.ground_friction);
        Fighter_PhysGround_ApplyFriction(gobj);
    }}
    else
    {{
        Qd_Brake(&fd->phys.self_vel.X, QD_BRAKE_AIR);
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
    }}
}}
void QdEnd_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Leave(gobj);
}}

// Aether after the rise: straight down with the sword until he lands, catching a ledge he faces on the way
void Plunge_Phys(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    fd->phys.self_vel.X = 0;
    fd->phys.self_vel.Y = -PLUNGE_SPEED;
}}
void Plunge_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Enter(gobj, ST_PLUNGE);
}}
static void Plunge_Landed(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    Fighter_SetGrounded2(fd);
    Enter(gobj, ST_SLAM);
}}
void Plunge_Coll(GOBJ *gobj)
{{
    Fighter_CollAir_GrabFacingLedgeWalljump(gobj, LEDGE_CHECK, Plunge_Landed);
}}
void Slam_Anim(GOBJ *gobj)
{{
    if (FrameTimerCheck(gobj) == 0)
        Fighter_EnterWait(gobj);
}}
void Slam_Phys(GOBJ *gobj)
{{
    Fighter_PhysGround_ApplyFriction(gobj);
}}
void Slam_Coll(GOBJ *gobj)
{{
    Fighter_CollGround_StopLedge_EnterFall(gobj);
}}

static void OwnFrame(FighterData *fd, GOBJ *gobj)
{{
    int p = fd->ply, s = fd->state_id, was = last_state[p];
    last_state[p] = s;
    // the side special: the donor's state is left at once for the fighter's own
    if (s == ST_SIDE || s == ST_SIDE_AIR)
    {{
        qd_charge[p] = 0;
        Enter(gobj, Qd(fd, 0));
        last_state[p] = fd->state_id;
        return;
    }}
    // the up special: where the rise ends, the plunge begins
    if ((s == ST_UP || s == ST_UP_AIR) && fd->state.frame >= UP_LAST)
    {{
        if (fd->phys.air_state == 0)
            Fighter_SetAirborne(fd);
        Enter(gobj, ST_PLUNGE);
        last_state[p] = fd->state_id;
        return;
    }}
    // the neutral special let go at its fullest costs him some damage of his own
    if (({full_states}) && s != was)
        Fighter_GiveDamage(fd, RECOIL);
}}
'''


def ike(ctx):
    action, total, st = ctx['action'], ctx['total'], ctx['state']
    ground = ('SpecialS2Hi', 'SpecialS2Lw', 'SpecialS3Hi', 'SpecialS3S', 'SpecialS3Lw')
    air_ = ('SpecialAirS2Hi', 'SpecialAirS2Lw', 'SpecialAirS3Hi', 'SpecialAirS3S', 'SpecialAirS3Lw')
    need = ground + air_ + ('SpecialAirS4Hi', 'SpecialS4Hi', 'SpecialHi', 'SpecialAirHi')
    missing = [m for m in need if m not in action or not total.get(m)]
    if missing or 'SpecialS1' not in st or 'SpecialAirS1' not in st:
        return None, f'no clips on {missing}' if missing else 'the donor has no side special state to start from'
    first, world = ctx['first'], float(ctx['world'])
    on_ground, in_air = ctx['flags']['ground'], ctx['flags']['air']
    side_move, up_move = ctx['move'].get('side', ctx['move']['down']), ctx['move']['up']
    names = ('Quick Draw starts', 'Quick Draw is held', 'Quick Draw dashes', 'Quick Draw swings', 'Quick Draw ends')
    calls = ({'anim': 'QdStart_Anim', 'phys': 'Qd_Phys', 'coll': 'Qd_Coll'}, {'anim': 'QdHold_Anim', 'iasa': 'QdHold_IASA', 'phys': 'Qd_Phys', 'coll': 'Qd_Coll'},
             {'anim': 'QdDash_Anim', 'phys': 'QdDash_Phys', 'coll': 'QdDash_Coll'},
             {'anim': 'QdEnd_Anim', 'phys': 'QdSwing_Phys', 'coll': 'Qd_Coll'}, {'anim': 'QdEnd_Anim', 'phys': 'QdEnd_Phys', 'coll': 'Qd_Coll'})
    rows = [dict({'name': n, 'action': action[m], 'flags': on_ground, 'move': side_move}, **c) for n, m, c in zip(names, ground, calls)]
    rows += [dict({'name': n + ' in the air', 'action': action[m], 'flags': in_air, 'move': side_move}, **c)
             for n, m, c in zip(names, air_, calls)]
    rows += [{'name': "Aether's plunge", 'action': action['SpecialAirS4Hi'], 'flags': in_air, 'move': up_move,
              'anim': 'Plunge_Anim', 'phys': 'Plunge_Phys', 'coll': 'Plunge_Coll'},
             {'name': "Aether's slam", 'action': action['SpecialS4Hi'], 'flags': on_ground, 'move': up_move,
              'anim': 'Slam_Anim', 'phys': 'Slam_Phys', 'coll': 'Slam_Coll'}]
    # the side special's numbers: the game names the table, not what each number in it is. Read here as: [0] the
    # frames of charge that count, [2] and [3] the dash's speed on the ground and in the air, [4] and [5] what a
    # frame of charge adds to each, [6] what it adds to the swing's damage (9 and 0.1 over 70 frames is the
    # published 9 to 16), [9] what is left of the dash's speed as its end begins and [10], [11] what each frame of
    # the end takes off it on the ground and in the air. The last three are a reading with nothing to name them:
    # they are the ones that give the published distances (a tap about half a stage: 16 frames at 4.2 and a stop
    # from 2.1 at 0.3 a frame; a full charge nearly all of it), where ordinary friction gives twice that.
    qd = (ctx.get('own_params') or {}).get('paramIkeSpecialS__9ftIkeNode') or []
    value = lambda i, default: float(qd[i]) if len(qd) > i and isinstance(qd[i], (int, float)) else default
    moves = ctx.get('moves') or {}
    swing = moves.get('game_specialsattack') or {}
    hits = [h['damage'] for h in swing.get('hitboxes') or []]
    plunge = next((abs(y) for _f, _x, y in (moves.get('game_specialhi3') or {}).get('momentum') or [] if y), 6.0)
    charge = ctx.get('charge') or {}
    full = ' || '.join(f's == {int(x)}' for x in charge.get('full', ())) or '0'
    source = IKE.format(
        qd=first, plunge=first + 10, slam=first + 11, side=st['SpecialS1'], side_air=st['SpecialAirS1'],
        up=st['SpecialHi'], up_air=st['SpecialAirHi'],
        qd_max=int(value(0, 70)), qd_speed=value(2, 4.2) * world, qd_speed_air=value(3, 3.6) * world,
        qd_gain=value(4, 0.06) * world, qd_gain_air=value(5, 0.04) * world,
        qd_damage=float(max(hits)) if hits else 9.0, qd_damage_gain=value(6, 0.1),
        qd_reach=value(15, 9.0) * world, qd_tall=value(17, 9.0) * world,
        qd_swing_speed=next((x for _f, x, _y in swing.get('momentum') or [] if x), 1.0) * world,
        qd_end=value(9, 0.5), qd_brake=value(10, 0.3) * world, qd_brake_air=value(11, 0.1) * world,
        plunge_speed=plunge * world, up_last=max(2, int(total['SpecialHi']) - 1),
        fall_lag=int(total.get('LandingFallSpecial') or 20),
        recoil=float(charge.get('recoil') or 0.0), full_states=full)
    return {'source': source.strip('\n').split('\n'), 'rows': rows, 'load': ['OwnLoad(fd);'], 'frame': ['OwnFrame(fd, gobj);'],
            'entries': [first, first + 5],
            'provides': ['Quick Draw: a charge held, a dash by the charge, a swing at the first fighter reached',
                         "Aether's plunge after the rise, a ledge caught on the way down, the slam on landing",
                         'a full charge of the neutral special costs the fighter damage of its own']}, None


class _FromItsModule(dict):
    """A table by fighter that also answers for ANY fighter with a module of its own states: what `read` takes from
    that module (`fighters.specials`: fighter_port/own_<fighter>.py, found by its name). So a new fighter on its own
    skeleton is written into no table here: its module is the one place (`own_template.py` is found this
    way). The rows given outright are the fighters on the donor's skeleton, whose states are functions above."""

    def __init__(self, given, read):
        super().__init__(given)
        self._read = read

    def __missing__(self, fighter):
        from . import fighters
        module = fighters.specials(fighter) if isinstance(fighter, str) else None
        if module is None:
            raise KeyError(fighter)
        return self._read(module)

    def __contains__(self, fighter):
        try:
            self[fighter]
        except KeyError:
            return False
        return True

    def get(self, fighter, default=None):
        try:
            return self[fighter]
        except KeyError:
            return default


BUILD = _FromItsModule({'cloud': cloud, 'master': master, 'ike': ike}, lambda module: module.build)
# A fighter on its own skeleton whose specials are all states of its own: {clip name: donor action} for their
# clips (its module's `CLIPS`). They are given to the spec by the own-skeleton route only when the states are
# built (`own_route.run`), so a run that cannot build them (no MexTK) is the same as it was. (`CLIPS` above is for
# a port on the donor's skeleton, where the driver's spec always reads it.)
OWN_CLIPS = _FromItsModule({}, lambda module: dict(getattr(module, 'CLIPS', None) or {}))
# The actions of a fighter's own special states in which the fighter itself strikes (its module's `HIT_ACTIONS`):
# the own-skeleton route writes their hitboxes from the game's scripts for their clips (`own_route.run`). A fighter
# whose specials strike only with the items they make has none. (Duck Hunt's do; Wolf was the first to need it.)
SPECIAL_HITS = _FromItsModule({}, lambda module: tuple(getattr(module, 'HIT_ACTIONS', None) or ()))


def code_sounds(fighter):
    """The sounds of a fighter's that its own code plays (its items, its own states), in the order they matter when
    its bank is short of room: each needs a place in the bank that code can call (`voice.choose`). Its module's
    `CODE_SOUNDS`."""
    from . import fighters
    return list(getattr(fighters.specials(fighter), 'CODE_SOUNDS', None) or ())


def code_effects(fighter):
    """{action: names of the fighter's own effects} that its own code plays in that action's state instead of the
    script (its module's `CODE_EFFECTS`): the route leaves those calls out of the script. (Wolf's Fire Wolf: the
    fire follows a joint his code turns to the flight, which the engine's held effects do not turn with.)"""
    from . import fighters
    return {k: tuple(v) for k, v in (getattr(fighters.specials(fighter), 'CODE_EFFECTS', None) or {}).items()}


def hand_stand_ins(fighter):
    """[(effect set, emitter name)] of the emitters that draw on a 3D shape for which the fighter's module makes its
    own stand-in (its `HAND_STAND_INS`): the effect plan leaves them out instead of flattening their shapes
    (`own_effects.Plan.by_hand`). (Wolf's sheath of fire, a glow on each joint of his body.)"""
    from . import fighters
    return [tuple(pair) for pair in getattr(fighters.specials(fighter), 'HAND_STAND_INS', None) or ()]


def names(fighter):
    """The names of the values of a fighter's own parameter file that its states read (the file holds hashes). Its
    module's `NAMES`."""
    from . import fighters
    return list(getattr(fighters.specials(fighter), 'NAMES', None) or ())


def build(fighter, ctx):
    """-> (what the code file needs for this fighter's own states, or None; why not)."""
    if fighter not in BUILD:
        return None, None
    return BUILD[fighter](ctx)
