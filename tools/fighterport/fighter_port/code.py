"""The port's compiled code file: what the game only does for its own fighters.

Some things the game decides by its built-in list of fighters, and a fighter
added through m-ex gets none of them unless it brings a function for it. The
functions live in an `ftFunction` root appended to the fighter's data file,
compiled from C by MexTK (the kit is the `MexTK` folder of github.com/akaneia/m-ex:
MexTK.exe, mex.h, include/, melee.link; devkitPPC does the compiling). The app's
own `vault.echo.tier2.build` runs the tool and appends the result without
disturbing the file's other bytes.

What is written here so far:

  * sword trail data. The trail's script command draws nothing for a new
    fighter: ftafterimage.c picks the trail's shape and colours by fighter
    kind. m-ex asks the fighter's `GetTrailData` instead, and a donor that has
    a trail keeps its description at a fixed place in its special attributes,
    which the port still carries.

  * a projectile for the neutral special (`shot`): the donor's own special keeps
    running (Marth's start, charge loop and release), its release script raises a
    flag, and a per-frame function lets an item go from the weapon joint. The
    item's behaviour is a second small file built into an `itFunction` root, the
    way the toolkit's Mario example builds his fireball. The item's data is
    `items.py`'s business.
"""
from __future__ import annotations

import os
from pathlib import Path

# where a donor's special attributes hold its sword trail description (ftafterimage.c)
TRAIL_ATTR = {'Marth': 0x78, 'Roy': 0x78, 'Link': 0x64, 'Young Link': 0x64}


def toolkit(folder=None):
    """The MexTK folder to build with, or None when there is none on this machine."""
    for c in (folder, os.environ.get('MEXTK_DIR')):
        if c and (Path(c) / 'MexTK.exe').is_file() and (Path(c) / 'mex.h').is_file():
            return Path(c)
    return None


def donor_trail(pl_bytes: bytes, donor, Dat):
    """The donor's own trail description, read from its data file, or None."""
    import struct
    if donor not in TRAIL_ATTR:
        return None
    d = Dat(pl_bytes)
    ft = next(off for name, off in d.roots if name.startswith('ftData'))
    at = 0x20 + d.ptr(ft + 4) + TRAIL_ATTR[donor]
    raw = bytes(d.buf[at:at + 0x20])
    x0, x4 = struct.unpack_from('>ff', raw, 0)
    bone, bottom, top = struct.unpack_from('>iff', raw, 0x14)
    return {'x0': x0, 'x4': x4, 'start_alpha': raw[8], 'end_alpha': raw[9], 'in_col': list(raw[0xA:0xE]),
            'out_col': list(raw[0xE:0x12]), 'x12': raw[0x12], 'x13': raw[0x13], 'bone': bone, 'bottom': bottom, 'top': top}


def shot_source(shot, load=()):
    """C for a projectile special. `shot`: joint (the shots leave from), flag (0..3, raised by
    the release script), onload (the donor's own load function, called first), and `shots`,
    a list of {item (index), states (the donor states in which it is the one let go), pierce, and
    optionally rise: a shot that stands on the ground starts that far above the fighter's base, not at the joint;
    variant: which version of the shot it is, when `shot['variant']` (a C expression from the port's own code)
    says which is being let go; trap {life}: it stops on what it hits and its second state hits on for that long}.
    -> (lines for fighter.c, {item index: text of that item's file})"""
    shots = shot['shots']
    beam = next((sh for sh in shots if sh.get('beam')), None)
    fighter = [
        '// The neutral special lets an item of the fighter\'s own go when the move\'s script raises a flag.',
        f"#define SHOT_JOINT {int(shot['joint'])}",
        'typedef struct ShotAttr { float speed; float life; } ShotAttr;   // the item\'s own attributes (items.py)',
        '',
        'void OnLoad(GOBJ *gobj)',
        '{',
        '    FighterData *fd = gobj->userdata;',
        f"    ((void (*)(GOBJ *)){int(shot['onload']):#x})(gobj);                 // the donor's own",
        *['    ' + line for line in load],
        *(['    beam_age[fd->ply] = 0;', '    beam_drawn[fd->ply] = 0;'] if beam else []),
        '    ItemDesc **items = fd->ftData->items;',
        '    if (!items)',
        '        return;']
    for sh in shots:
        fighter += [f"    if (items[{int(sh['item'])}])",
                    f"        MEX_IndexFighterItem(fd->kind, items[{int(sh['item'])}], {int(sh['item'])});"]
    fighter += [
        '}',
        '',
        'static void Shoot(GOBJ *gobj, int which, float rise)',
        '{',
        '    FighterData *fd = gobj->userdata;',
        '    Vec3 from, centre;',
        '    JOBJ_GetWorldPosition(fd->bones[SHOT_JOINT].joint, 0, &from);',
        '    Fighter_GetECBPosition(gobj, &centre);',
        '    SpawnItem spawn;',
        '    spawn.parent_gobj = gobj;',
        '    spawn.parent_gobj2 = gobj;',
        '    spawn.it_kind = MEX_GetFtItemID(gobj, which);',
        '    spawn.pos = centre;',
        '    spawn.pos2.X = from.X;',
        '    spawn.pos2.Y = rise < 0 ? from.Y : fd->phys.pos.Y + rise;      // at the joint, or standing on the fighter\'s ground',
        '    spawn.pos2.Z = 0;',
        '    spawn.vel.X = 0;',
        '    spawn.vel.Y = 0;',
        '    spawn.vel.Z = 0;',
        '    spawn.facing_direction = fd->facing_direction;',
        '    spawn.damage = 0;',
        '    spawn.unk6 = 0;',
        '    spawn.is_raycast_below = 1;',
        '    GOBJ *item = Item_CreateItem1(&spawn);',
        '    if (!item)',
        '        return;',
        '    ItemData *id = item->userdata;',
        '    ShotAttr *attr = (ShotAttr *)id->itData->param_ext;',
        '    id->self_vel.X = attr->speed * id->facing_direction;',
        '    id->self_vel.Y = 0;',
        '    id->self_vel.Z = 0;',
        '    // it moves twice before its hitbox is first checked: start it that far back, so the first check is where it leaves',
        '    id->pos.X -= 2.0f * id->self_vel.X;',
        '    Item_SetLifeTimer(item, attr->life);',
        '    ItemStateChange(item, 0, 2);',
        '    Item_CopyDevelopState(item, gobj);',
        '    Item_UpdatePhysAndColl(item);',
        '    JOBJ *model = item->hsd_object;                 // built pointing right: turned when it is let go to the left',
        '    model->rot.Y = id->self_vel.X < 0 ? 3.14159265f : 0;',
        '    JOBJ_SetMtxDirtySub(model);',
        *(['    if (which == BEAM_ITEM)',
           '    {',
           '        beam_from[fd->ply] = spawn.pos2;',
           '        beam_way[fd->ply] = fd->facing_direction;',
           '        beam_age[fd->ply] = 1;',
           '    }'] if beam else []),
        '}',
        '',
        'static void ShotFrame(FighterData *fd, GOBJ *gobj)',
        '{',
        '    int s = fd->state_id;',
        f"    if (!fd->ftcmd_var.flag{int(shot['flag'])})",
        '        return;']
    for sh in shots:
        states = ' || '.join(f's == {int(x)}' for x in sh['states'])
        if shot.get('variant'):                         # the port's own code says which version of the shot this is
            states = f"({states}) && ({shot['variant']}) == {int(sh.get('variant') or 0)}"
        fighter += [f'    if ({states})',
                    '    {',
                    f"        fd->ftcmd_var.flag{int(shot['flag'])} = 0;",
                    f"        Shoot(gobj, {int(sh['item'])}, {float(sh['rise']) if sh.get('rise') is not None else -1.0:.2f}f);",
                    '        return;',
                    '    }']
    fighter += ['}', '']
    if beam:
        # the streak's three layers, widest first: half its height as a share of the whole, its colour (the
        # drawing routine multiplies a colour by itself, so the roots are given), how see-through
        look = beam['beam']
        root = lambda v: int(round(255.0 * (max(0, min(255, v)) / 255.0) ** 0.5))
        r, g, b = (root(v) for v in look['colour'])
        beam_lines = [
            '// A shot that crosses the stage in a few frames is seen as a beam of light, not as a thing that flies: a',
            '// streak from where it was let go to where it has got to, which fades once the shot is gone. It is drawn',
            "// after the fighter itself, in the fighter's own drawing (see-through shapes go in the last pass).",
            f"#define BEAM_ITEM {int(beam['item'])}",
            f"#define BEAM_SPEED {float(look['speed'])!r}f",
            f"#define BEAM_LIFE {float(look['life'])!r}f               // frames the shot flies",
            f"#define BEAM_FADE {float(look.get('fade', 16.0))!r}f               // frames the streak takes to fade after that",
            f"#define BEAM_HALF {float(look['half'])!r}f               // half the streak's height",
            '#ifndef DRAW_RECT',
            '#define DRAW_RECT ((void (*)(Vec3 *, Vec3 *, GXColor *))0x80009DD4)                                 // lbColl_80009DD4',
            '#endif',
            'static Vec3 beam_from[6];',
            'static float beam_way[6];',
            'static u8 beam_age[6];                  // frames since the shot was let go (0: no streak)',
            'static void (*beam_drawn[6])(GOBJ *, int);      // the drawing of the fighter that this goes after',
            '',
            'static void Beam_Draw(GOBJ *gobj, int pass)',
            '{',
            '    FighterData *fd = gobj->userdata;',
            '    int p = fd->ply, i;',
            '    if (beam_drawn[p])',
            '        beam_drawn[p](gobj, pass);',
            '    if (pass != 2 || !beam_age[p])',
            '        return;',
            '    {',
            '        float age = (float)beam_age[p];',
            '        float reach = BEAM_SPEED * (age < BEAM_LIFE ? age : BEAM_LIFE);',
            '        float fade = age <= BEAM_LIFE ? 1.0f : 1.0f - (age - BEAM_LIFE) / BEAM_FADE;',
            '        float x0 = beam_from[p].X, x1 = x0 + beam_way[p] * reach;',
            '        static const float half[3] = {BEAM_HALF, BEAM_HALF * 0.55f, BEAM_HALF * 0.2f};',
            f"        GXColor c[3] = {{{{{r}, {g}, {b}, 185}}, {{{r}, {root((look['colour'][1] + 255) // 2)}, {root((look['colour'][2] + 255) // 2)}, 235}}, {{255, 255, 244, 255}}}};",
            '        if (fade < 0.0f)',
            '            fade = 0.0f;',
            '        for (i = 0; i < 3; i++)',
            '        {',
            '            Vec3 a, b;',
            '            c[i].a = (u8)((float)c[i].a * fade);',
            '            a.X = x0 < x1 ? x0 : x1;',
            '            b.X = x0 < x1 ? x1 : x0;',
            '            a.Y = beam_from[p].Y - half[i];',
            '            b.Y = beam_from[p].Y + half[i];',
            '            a.Z = fd->phys.pos.Z + 4.0f + 0.2f * (float)i;',
            '            b.Z = a.Z;',
            '            DRAW_RECT(&a, &b, &c[i]);',
            '        }',
            '    }',
            '}',
            '',
            'static void BeamFrame(FighterData *fd, GOBJ *gobj)',
            '{',
            '    int p = fd->ply;',
            '    if (!beam_drawn[p] && gobj->gx_cb)              // once: put after the drawing the fighter has now',
            '    {',
            '        beam_drawn[p] = (void (*)(GOBJ *, int))gobj->gx_cb;',
            '        gobj->gx_cb = (void (*)())Beam_Draw;',
            '    }',
            '    if (beam_age[p] && ++beam_age[p] > (u8)(BEAM_LIFE + BEAM_FADE))',
            '        beam_age[p] = 0;',
            '}',
            '']
        # its variables and drawing come before the code that uses them (the load function clears them)
        at = fighter.index('void OnLoad(GOBJ *gobj)')
        fighter[at:at] = beam_lines
    files = {}
    for sh in shots:
        gone = 'false' if sh.get('pierce') else 'true'
        if sh.get('trap'):
            # a shot that holds what it hits: it stops there, and its second state's script hits again and again
            files[int(sh['item'])] = chr(10).join([
                '#include "../mex.h"',
                '',
                '// A shot that holds what it hits: it flies straight until it hits, stops there, hits again and',
                '// again (its second state\'s script) and ends.',
                f"#define HOLD_FRAMES {float(sh['trap']['life'])!r}f",
                f"#define HOLD_AHEAD {float(sh['trap'].get('ahead') or 0.0)!r}f      // it stops short of what it hit by this much, and steps on to it",
                '// (Its second state starts on the frame after the hit: a hitbox made during the hit itself would',
                '// count what it has just hit as hit already.)',
                'bool OnGiveDamage(GOBJ *item)',
                '{',
                '    ItemData *id = item->userdata;',
                '    if (id->state == 0)',
                '    {',
                '        id->self_vel.X = 0;',
                '        id->self_vel.Y = 0;',
                '        id->itcmd_var.flag1 = 1;',
                '    }',
                '    return false;',
                '}',
                'bool OnHitShieldBounce(GOBJ *item) { return true; }',
                'bool OnHitShieldDetermineDestroy(GOBJ *item) { return true; }',
                'bool OnClank(GOBJ *item) { return true; }',
                'bool OnReflect(GOBJ *item)',
                '{',
                '    Item_ReflectVelocity(item);',
                '    return false;',
                '}',
                '',
                '// Its model points the way it flies (it is built pointing right).',
                'static void Face(GOBJ *item)',
                '{',
                '    ItemData *id = item->userdata;',
                '    JOBJ *model = item->hsd_object;',
                '    if (id->self_vel.X == 0)',
                '        return;',
                '    model->rot.Y = id->self_vel.X < 0 ? 3.14159265f : 0;',
                '    JOBJ_SetMtxDirtySub(model);',
                '}',
                '',
                '// While it holds, each hit stops it for as much of the usual pause as the game gives these hits.',
                f"#define HOLD_LAG {float(sh['trap'].get('lag', 1.0))!r}f",
                'static void Hold_Lag(GOBJ *item)',
                '{',
                '    ItemData *id = item->userdata;',
                '    id->dmg.hitlag_remaining *= HOLD_LAG;',
                '    if (id->dmg.hitlag_remaining < 1.0f)',
                '        id->dmg.hitlag_remaining = 1.0f;',
                '}',
                '',
                'int Shot_Anim(GOBJ *item)',
                '{',
                '    ItemData *id = item->userdata;',
                '    Face(item);',
                '    if (id->state == 0 && id->itcmd_var.flag1)',
                '    {',
                '        id->pos.X += HOLD_AHEAD * id->facing_direction;',
                '        id->itcmd_var.flag1 = 0;',
                '        ItemStateChange(item, 1, 2);',
                '        // each hit stops its script for a few frames, so the script itself says when it is over',
                '        // (it raises the same variable at its end); the timer is only there in case it never does',
                '        Item_SetLifeTimer(item, 4.0f * HOLD_FRAMES);',
                '        id->cb.on_enter_hitlag = Hold_Lag;',
                '        return 0;',
                '    }',
                '    if (id->state == 1 && id->itcmd_var.flag1)',
                '        return 1;',
                '    return Item_DecLifeTimer(item);',
                '}',
                'void Shot_Phys(GOBJ *item) {}',
                'int Shot_Coll(GOBJ *item) { return (Item_CollAir_NoCB(item)' + (' & ~1' if sh.get('rise') is not None else '') + ') != 0; }',
                'int Hold_Coll(GOBJ *item) { return 0; }',
                '',
                '__attribute__((used))',
                'static struct ItemState item_state_table[] = {',
                '    {.state = 0, .animCallback = Shot_Anim, .physCallback = Shot_Phys, .collCallback = Shot_Coll},',
                '    {.state = 1, .animCallback = Shot_Anim, .physCallback = Shot_Phys, .collCallback = Hold_Coll},',
                '};',
                ''])
            continue
        files[int(sh['item'])] = chr(10).join([
            '#include "../mex.h"',
            '',
            '// A shot: flies straight at the speed it was let go with until its life runs out'
            + (' (it goes on through what it hits).' if sh.get('pierce') else ' or it hits.'),
            f'bool OnGiveDamage(GOBJ *item) {{ return {gone}; }}',
            'bool OnHitShieldBounce(GOBJ *item) { return true; }',
            'bool OnHitShieldDetermineDestroy(GOBJ *item) { return true; }',
            'bool OnClank(GOBJ *item) { return true; }',
            'bool OnReflect(GOBJ *item)',
            '{',
            '    Item_ReflectVelocity(item);',
            '    return false;',
            '}',
            '',
            '// Its model points the way it flies (it is built pointing right).',
            'static void Face(GOBJ *item)',
            '{',
            '    ItemData *id = item->userdata;',
            '    JOBJ *model = item->hsd_object;',
            '    if (id->self_vel.X == 0)',
            '        return;',
            '    model->rot.Y = id->self_vel.X < 0 ? 3.14159265f : 0;',
            '    JOBJ_SetMtxDirtySub(model);',
            '}',
            '',
            'int Shot_Anim(GOBJ *item)',
            '{',
            '    Face(item);',
            '    return Item_DecLifeTimer(item);',
            '}',
            'void Shot_Phys(GOBJ *item) {}',
            # it ends at a wall or a ceiling; one that stands on the ground runs along the floor, any other ends there too
            'int Shot_Coll(GOBJ *item) { return (Item_CollAir_NoCB(item)' + (' & ~1' if sh.get('rise') is not None else '') + ') != 0; }',
            '',
            '__attribute__((used))',
            'static struct ItemState item_state_table[] = {',
            '    {.state = 0, .animCallback = Shot_Anim, .physCallback = Shot_Phys, .collCallback = Shot_Coll},',
            '};',
            ''])
    return fighter, files


def source(donor, trail=None, shot=None, armour=None, tether=None, slides=None, own=None, onload=None, reverse=None,
           chain=None, counter=None, flash=None, state_rows=None, momentum=None, jabs=None):
    """{file name: C text} for a port on `donor`, and the list of what it provides.
    `trail` is a full trail description (the keys `donor_trail` returns) to use
    instead of the donor's own; `shot` a projectile special (see `shot_source`); `armour`
    {states, first, last}: donor states and clip frames between which hits do not stagger;
    `tether` {state, first, last, width, y, height}: the ledge catch box while a whip is out;
    `slides` the actions (indices) whose clip travels along the ground in a donor state that only slows
    the fighter down; `own` the port's own states (`own.build`, with `table`: the state table's lines, and
    optionally `items`: [{code: C text}] for the items those states make);
    `onload` the donor's own load function, called first when the port has things to set up;
    `reverse` the states a special starts in: held the other way on its first frames, the stick turns it around
    (a state number, or (state, the last of its frames that still counts) for a state the move reaches part-way
    into those first frames);
    `chain` {states, flag}: the states of a chained special whose donor shuts the chain when the button is
    pressed before a step's window opens (it keeps that in a script flag): the fighter being ported has no such rule.
    `flash` [(action, frame, frames to get there, colour from, colour to)]: the colour a move lays over the body.
    state_rows (donor rows, own rows) is required with reversal: IASA is wrapped after input refresh.
    A file named item_<index>.c is that item's code."""
    from . import states as state_tools
    table_rows = tuple([dict(row) for row in group] for group in state_rows) if state_rows is not None else None
    if reverse and table_rows is None:
        raise ValueError('special reversal needs the donor and own state rows to wrap current-input IASA')
    if jabs and onload is None and not shot:
        raise ValueError('source jab listeners require the donor OnLoad callback')
    if momentum:
        if onload is None and not shot:
            raise ValueError('source velocity events require the donor OnLoad callback')
        overlap = sorted({e['action'] for e in momentum} & set(slides or []))
        if overlap:
            raise ValueError(f'source velocity and animation travel both own actions {overlap}; resolve movement ownership')
    parts, provides = ['#include "../mex.h"', ''], []
    extra = {}
    loads = list((own or {}).get('load') or [])
    frame = []                                          # what the per-frame function does, in order
    if own:
        parts += list(own['source']) + ['']
        frame += list(own['frame'])
        provides += list(own['provides'])
        # the items the port's own states make: each one's code is a file of its own (its place in the list is its number)
        extra.update({f'item_{i}.c': item['code'] for i, item in enumerate(own.get('items') or []) if item.get('code')})
    if jabs:
        from . import own_jab
        parts += own_jab.source(jabs) + ['']
        loads.append('Jab_Load(fd);')
        frame.append('Jab_Frame(fd);')
        provides.append('source jab listener intervals on current input')
    if momentum:
        from . import own_momentum
        parts += own_momentum.source(momentum) + ['']
        loads.append('Momentum_Load(fd);')
        frame.append('Momentum_Register(fd, gobj);')
        provides.append('ordinary source velocity events after input and before collision')
    if shot:
        lines, item_files = shot_source(shot, loads)
        parts += lines
        extra.update({f'item_{i}.c': text for i, text in item_files.items()})
        frame.append('ShotFrame(fd, gobj);')
        if any(sh.get('beam') for sh in shot['shots']):
            frame.append('BeamFrame(fd, gobj);')
            provides.append('a shot that crosses the stage in a few frames is drawn as a beam of light')
        provides.append('a projectile for the neutral special' if len(item_files) == 1 else
                        f'{len(item_files)} projectiles for the neutral special')
    if armour and isinstance(armour, dict):
        states = ' || '.join(f'fd->state_id == {int(x)}' for x in armour['states'])
        parts += [
            '// A special that cannot be knocked out of its swing: armour while its clip is between two frames.',
            f"#define ARMOUR {float(armour.get('amount', 4321.0))!r}f      // more than any hit's knockback; also how this code knows its own",
            'static void ArmourFrame(FighterData *fd)',
            '{',
            # this runs before the frame's clip moves on: the clip frame a hit will find is one more than it reads here
            f"    if (({states}) && fd->state.frame + 1.0f >= {float(armour['first'])!r}f && fd->state.frame + 1.0f <= {float(armour['last'])!r}f)",
            '        fd->dmg.armor = ARMOUR;',
            '    else if (fd->dmg.armor == ARMOUR)',
            '        fd->dmg.armor = 0;',
            '}',
            '']
        frame.append('ArmourFrame(fd);')
        provides.append('armour on the down special')
    elif armour:
        # several stretches, each of some states or some actions between two frames of its clip
        tests = []
        for span in armour:
            who = ' || '.join([f'fd->state_id == {int(x)}' for x in span.get('states', ())]
                              + [f'a == {int(x)}' for x in span.get('actions', ())])
            tests += [f"    if (({who}) && at >= {float(span['first'])!r}f && at <= {float(span['last'])!r}f)",
                      '        on = 1;']
        parts += [
            '// Moves that cannot be knocked out of: armour while their clips are between the frames the game gives.',
            '#define ARMOUR 4321.0f      // more than any hit\'s knockback; also how this code knows its own',
            'static void ArmourFrame(FighterData *fd)',
            '{',
            '    int on = 0, a = fd->action_id;',
            "    float at = fd->state.frame + 1.0f;      // this runs before the frame's clip moves on: the frame a hit will find",
            *tests,
            '    if (on)',
            '        fd->dmg.armor = ARMOUR;',
            '    else if (fd->dmg.armor == ARMOUR)',
            '        fd->dmg.armor = 0;',
            '}',
            '']
        frame.append('ArmourFrame(fd);')
        provides.append('armour on the frames the game gives it')
    if counter:
        which = ' || '.join(f'a == {int(i)}' for i in counter['actions'])
        parts += [
            '// A counter strikes back for what it took, times the fighter\'s own number and no less than its least. The',
            '// donor keeps what it took (times the number in its data) and its script makes the hit: the damage is put on',
            '// that hit in the state\'s own step, after the script has made it and before it strikes anything.',
            f"#define COUNTER_LEAST {int(counter['least'])}",
            'static void (*counter_step[6])(GOBJ *);',
            'static void Counter_Phys(GOBJ *gobj)',
            '{',
            '    FighterData *fd = gobj->userdata;',
            '    int i, damage = fd->state_var.state_var1;',
            '    if (counter_step[fd->ply])',
            '        counter_step[fd->ply](gobj);',
            '    if (damage < COUNTER_LEAST)',
            '        damage = COUNTER_LEAST;',
            '    for (i = 0; i < 4; i++)',
            '        if (fd->hitbox[i].active)',
            '            Fighter_UpdateHitboxDamage(&fd->hitbox[i], damage, gobj);',
            '}',
            'static void CounterFrame(FighterData *fd)',
            '{',
            '    int a = fd->action_id;',
            f'    if (({which}) && (void *)fd->cb.Phys != (void *)Counter_Phys)',
            '    {',
            '        counter_step[fd->ply] = fd->cb.Phys;',
            '        fd->cb.Phys = Counter_Phys;',
            '    }',
            '}',
            '']
        frame.append('CounterFrame(fd);')
        provides.append("a counter that strikes back by the fighter's own multiple")
    if tether:
        parts += [
            '// A whip thrown towards a ledge: while it is out, the fighter\'s ledge catch reaches as far as the whip does.',
            '// (The donor\'s own air up special catches a ledge when its script flags say so; the script raises them.)',
            f"#define TETHER_X {float(tether['width'])!r}f",
            'static void TetherFrame(FighterData *fd)',
            '{',
            '    FtCollDesc *own = fd->ftData->coll;',
            f"    if (fd->state_id == {int(tether['state'])} && fd->state.frame >= {float(tether['first'])!r}f"
            f" && fd->state.frame <= {float(tether['last'])!r}f)",
            '    {',
            '        fd->coll_data.cliffgrab_width = TETHER_X;',
            f"        fd->coll_data.cliffgrab_y_offset = {float(tether['y'])!r}f;",
            f"        fd->coll_data.cliffgrab_height = {float(tether['height'])!r}f;",
            '    }',
            '    else if (fd->coll_data.cliffgrab_width == TETHER_X)',
            '    {',
            '        fd->coll_data.cliffgrab_width = own->cliffgrab_width;',
            '        fd->coll_data.cliffgrab_y_offset = own->cliffgrab_y_offset;',
            '        fd->coll_data.cliffgrab_height = own->cliffgrab_height;',
            '    }',
            '}',
            '']
        frame.append('TetherFrame(fd);')
        provides.append('a ledge catch as far as the whip reaches')
    if chain:
        which = ' || '.join(f's == {int(i)}' for i in chain['states'])
        parts += [
            "// The donor shuts its chain for good when the button is pressed before a step's window opens.",
            '// The fighter ported here has no such rule: what the donor notes of an early press is wiped each frame.',
            'static void ChainFrame(FighterData *fd)',
            '{',
            '    int s = fd->state_id;',
            f'    if ({which})',
            f"        fd->ftcmd_var.flag{int(chain['flag'])} = 0;",
            '}',
            '']
        frame.append('ChainFrame(fd);')
        provides.append('a chain that a button pressed early does not shut')
    if reverse:
        by_last = {}
        for r in reverse:
            state, last = (r, 4) if isinstance(r, int) else r
            by_last.setdefault(int(last), []).append(int(state))
        if list(by_last) == [4]:
            which = ' || '.join(f's == {i}' for i in by_last[4])
            test = f'    if (!({which}) || fd->state.frame > 4.0f)'
        else:
            # a move that runs through several states in its first frames: each state up to its own frame
            test = '    if (!(' + ' || '.join(
                '((' + ' || '.join(f's == {i}' for i in states) + f') && fd->state.frame <= {float(last)!r}f)'
                for last, states in sorted(by_last.items(), reverse=True)) + '))'
        parts += [
            '// A special can be turned around as it starts: the stick held the other way on its first frames',
            '// (the game lets any special be reversed like this; in the air what speed he has turns with him).',
            'static void ReverseInput(FighterData *fd, GOBJ *gobj)',
            '{',
            '    int s = fd->state_id;',
            test,
            '        return;',
            '    if (fd->input.lstick.X * fd->facing_direction < -0.5f)',
            '    {',
            '        fd->facing_direction = -fd->facing_direction;',
            '        fd->phys.self_vel.X = -fd->phys.self_vel.X;',
            '        Fighter_SetBoneRotY(fd, 0, 1.5707963f * fd->facing_direction);',
            '    }',
            '}',
            '']
        all_rows = table_rows[0] + table_rows[1]
        for state in dict.fromkeys(int(r if isinstance(r, int) else r[0]) for r in reverse):
            index = state - state_tools.FIRST_SPECIAL_STATE
            if not 0 <= index < len(all_rows):
                raise ValueError(f'reversal state {state} is outside the fighter state table')
            row = all_rows[index]
            name = f'Reverse_IASA_{state}'
            parts += state_tools.iasa_wrapper(name, 'ReverseInput', row.get('iasa'))
            row['iasa'] = name
        provides.append('specials that can be turned around as they start')
    if slides:
        which = ' || '.join(f'a == {int(i)}' for i in slides)
        parts += [
            '// Moves whose clip travels along the ground, in donor states that only slow the fighter down. The action',
            "// carries the engine's flag, so the clip's travel is taken out of the picture each frame; here the fighter",
            '// is given that travel as its ground speed (plus what the state\'s friction is about to take off it).',
            'static void TravelFrame(FighterData *fd)',
            '{',
            '    int a = fd->action_id;',
            f'    if (fd->phys.air_state != 0 || !({which}))',
            '        return;',
            '    float go = fd->transN_offset.Z * fd->facing_direction;',
            '    if (go > 0)',
            '        go += fd->attr.ground_friction;',
            '    else if (go < 0)',
            '        go -= fd->attr.ground_friction;',
            '    fd->phys.self_vel_ground.X = go;',
            '}',
            '']
        frame.append('TravelFrame(fd);')
        provides.append('moves that travel along the ground')
    if flash:
        rgba = lambda c: '{' + ', '.join(str(max(0, min(255, int(v)))) for v in c) + '}'
        parts += [
            '// The colour a move lays over the body, on the frames its script gives (a flash as a counter starts, a',
            '// pulse while a charge builds): the colour it starts from, the one it goes to and how many frames that takes.',
            "// The game draws it with the fighter's second colour overlay, which this leaves alone while the game is",
            '// using it. This runs before the frame is drawn and before its clip moves on: the frame about to be shown',
            '// is the second of an action the first time this sees it.',
            'typedef struct { short action, frame, fade; u8 from[4], to[4]; } FlashKey;',
            'static const FlashKey flash_keys[] = {',
            *[f'    {{{int(a_)}, {int(f_)}, {int(n_)}, {rgba(c0)}, {rgba(c1)}}},' for a_, f_, n_, c0, c1 in
              sorted(flash, key=lambda k: (k[0], k[1]))],
            '};',
            'static int flash_action[6], flash_state[6], flash_count[6];',
            'static u8 flash_lit[6];',
            'static void (*flash_anim[6])(GOBJ *);',
            "// Melee lays a colour animation of its own (the third: a green flicker) over a fighter whose script says it",
            "// cannot be hurt, and draws that in place of this overlay. A move that gives its own colour for those frames",
            "// shows its own: the game's is taken off after the frame's script has run (the state's own step is called",
            '// through this one, which is put in its place while an action with a colour of its own plays).',
            'static void Flash_Anim(GOBJ *gobj)',
            '{',
            '    FighterData *fd = gobj->userdata;',
            '    void (*then)(GOBJ *) = flash_anim[fd->ply];',
            '    if (flash_lit[fd->ply] && fd->color[0].colanim == 3)',
            '        ColAnim_Disable(&fd->color[0]);',
            '    if (then)',
            '        then(gobj);',
            '}',
            'static void FlashFrame(FighterData *fd)',
            '{',
            '    int p = fd->ply, i, t, has = 0;',
            '    const FlashKey *k = 0;',
            '    ColorOverlay *c = &fd->color[1];',
            '    if (fd->action_id != flash_action[p] || fd->state_id != flash_state[p])',
            '    {',
            '        flash_action[p] = fd->action_id;',
            '        flash_state[p] = fd->state_id;',
            '        flash_count[p] = 1;',
            '    }',
            '    if (fd->dmg.hitlag_frames <= 0.0f)        // a frame frozen by a hit is not a frame of the move',
            '        flash_count[p]++;',
            '    t = flash_count[p];',
            '    for (i = 0; i < (int)(sizeof(flash_keys) / sizeof(flash_keys[0])); i++)',
            '        if (flash_keys[i].action == fd->action_id)',
            '        {',
            '            has = 1;',
            '            if (flash_keys[i].frame <= t)',
            '                k = &flash_keys[i];',
            '        }',
            '    if (has && (void *)fd->cb.Anim != (void *)Flash_Anim)',
            '    {',
            '        flash_anim[p] = fd->cb.Anim;',
            '        fd->cb.Anim = Flash_Anim;',
            '    }',
            '    if (k && c->colanim == 0)',
            '    {',
            '        float s = k->fade > 0 ? (float)(t - k->frame) / (float)k->fade : 1.0f;',
            '        float v[4];',
            '        if (s > 1.0f)',
            '            s = 1.0f;',
            '        for (i = 0; i < 4; i++)',
            '            v[i] = (float)k->from[i] + ((float)k->to[i] - (float)k->from[i]) * s;',
            '        if (v[3] >= 1.0f)',
            '        {',
            '            if (fd->color[0].colanim == 3)        // (see Flash_Anim)',
            '                ColAnim_Disable(&fd->color[0]);',
            '            // (the game keeps the colour twice: numbers it steps every frame and the bytes it draws with)',
            '            c->color_red = v[0];',
            '            c->color_green = v[1];',
            '            c->color_blue = v[2];',
            '            c->color_alpha = v[3];',
            '            c->colorblend_red = 0;',
            '            c->colorblend_green = 0;',
            '            c->colorblend_blue = 0;',
            '            c->colorblend_alpha = 0;',
            '            c->hex.r = (u8)v[0];',
            '            c->hex.g = (u8)v[1];',
            '            c->hex.b = (u8)v[2];',
            '            c->hex.a = (u8)v[3];',
            '            c->color_enable = 1;',
            '            flash_lit[p] = 1;',
            '            return;',
            '        }',
            '    }',
            '    if (flash_lit[p])',
            '    {',
            '        c->color_enable = 0;',
            '        flash_lit[p] = 0;',
            '    }',
            '}',
            '']
        frame.append('FlashFrame(fd);')
        provides.append("the body's colour on the frames the game's scripts give")
    if loads and not shot:
        parts += ['void OnLoad(GOBJ *gobj)', '{', '    FighterData *fd = gobj->userdata;',
                  f"    ((void (*)(GOBJ *)){int(onload):#x})(gobj);                 // the donor's own"]
        parts += ['    ' + line for line in loads] + ['}', '']
    if frame:
        parts += ['void OnFrame(GOBJ *gobj)', '{', '    FighterData *fd = gobj->userdata;'] + ['    ' + f for f in frame] + ['}', '']
    if table_rows is not None:
        parts += state_tools.table_text(*table_rows)
    elif own:
        parts += list(own['table'])
    if trail:
        cols = lambda v: '{' + ', '.join(str(int(c)) for c in v) + '}'
        def desc(name, colour):
            return [f'static AfterImageDesc {name} = {{',
                    f"    .x0 = {trail['x0']!r}, .x4 = {trail['x4']!r}, .start_alpha = {trail['start_alpha']}, .end_alpha = {trail['end_alpha']},",
                    f"    .in_col = {cols(colour)}, .out_col = {cols(trail['out_col'])}, .x12 = {trail['x12']}, .x13 = {trail['x13']},",
                    f"    .bone_index = {trail['bone']}, .offset_bottom = {trail['bottom']:.3f}, .offset_top = {trail['top']:.3f},",
                    '};']
        parts += ["// The fighter's own sword trail: where the game's trail runs along the blade, in its trail's colour."]
        parts += desc('trail', trail['in_col'])
        pick = []
        for k, other in enumerate(trail.get('by_action') or []):
            # a move the game draws in another colour: its actions get that colour
            parts += desc(f'trail_{k + 1}', other['in_col'])
            pick += ['    if (' + ' || '.join(f'a == {int(i)}' for i in other['actions']) + ')', f'        return &trail_{k + 1};']
        parts += ['',
                  'AfterImageDesc *GetTrailData(GOBJ *fighter)',
                  '{']
        if pick:
            parts += ['    FighterData *fd = fighter->userdata;', '    int a = fd->action_id;'] + pick
        parts += ['    return &trail;',
                  '}',
                  '']
        provides.append("the fighter's own sword trail" + (f", in {len(pick) // 2 + 1} colours by move" if pick else ''))
    elif donor in TRAIL_ATTR:
        parts += [
            '// The donor keeps its sword trail description in its special attributes; the port carries those.',
            'AfterImageDesc *GetTrailData(GOBJ *fighter)',
            '{',
            '    FighterData *fd = fighter->userdata;',
            f'    return (AfterImageDesc *)((u8 *)fd->special_attributes + {TRAIL_ATTR[donor]:#x});',
            '}',
            '']
        provides.append('sword trail data')
    return ({'fighter.c': chr(10).join(parts), **extra} if provides else {}), provides


def build(pl_bytes: bytes, files: dict, kit) -> bytes:
    """`pl_bytes` with the compiled functions appended: fighter.c as its ftFunction root,
    and the item_<index>.c files together as its itFunction root."""
    import re
    import subprocess
    import tempfile
    from vault.echo import datroot
    from vault.echo.tier2 import build as tier2
    items = {int(re.fullmatch(r'item_(\d+)\.c', n)[1]): n for n in files if re.fullmatch(r'item_(\d+)\.c', n)}
    out = tier2.build_pl_from_files(pl_bytes, {n: t for n, t in files.items() if n not in items.values()},
                                    mextk_dir=str(kit))
    if items:
        with tempfile.TemporaryDirectory(prefix='port_items_') as tmp:
            src = Path(tmp) / 'src'
            src.mkdir()
            for n in items.values():
                (src / n).write_text(files[n], 'utf-8')
            made = Path(tmp) / 'itFunction.dat'
            cmd = [str(Path(kit) / 'MexTK.exe'), '-ff']
            for index, n in sorted(items.items()):
                cmd += ['-item', str(index), f'src/{n}']
            cmd += ['-s', 'itFunction', '-o', str(made), '-ow', '-q']
            r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
            if r.returncode or not made.is_file():
                raise tier2.BuildError('item code did not build:' + chr(10) + ((r.stdout or '') + (r.stderr or ''))[-1500:])
            data = made.read_bytes()
        if 'itFunction' not in [n for _, n in datroot.parse(data)[2]]:
            raise tier2.BuildError('the built item code has no itFunction root')
        out = datroot.merge_bytes(out, data)
    return out
