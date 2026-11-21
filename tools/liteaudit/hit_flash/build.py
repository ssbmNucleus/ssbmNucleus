"""The victim's body flash for Watch Lite (hitFlash.js): the colour animations a hit starts, run by the
game's own interpreter rule over PlCo.dat's scripts.

A hit that puts the victim into a damage state starts colour animation (ftCo_Damage.c ftCo_8008DA4C,
argument order read from the asm at 8008E1BC): fire 11 + class, electric 15 + class, ice 31 + class,
element 13 (dark) 35 + class, any other element 4. The class is the knockback x PlCo ftCommonData
x154 (0.4: the hitstun frames) below x158 / x15C / x160: 0, 1, 2, else 3; forced 3 when the damage code
is given a motion (ftCo_8008DCE0 arg1 != -1: a hit while down, frozen by ice).

The scripts are ftLoadCommonData [6] (ftcolanim.c ftCo_800BFFD0), an array of {script, priority, slot}.
Each call of lb_80014258 (lb_00F9.c) is one step: the wait timer counts down, and once it is 0 the
commands run until one waits again; then an active colour blend moves the colour one step. Commands:
the generic ones (lbcommand.c: 0 end, 3/4 loop, 5/6 subroutine, 7 goto), 0x0A done (the overlay is
cleared), 0x0B wait, 0x0C colour and light off, 0x0D/0x0E/0x0F/0x10/0x11 the light, 0x12 set colour,
0x13 blend to a colour over n steps ((0.5 + target - current) / n a step), 0x14 colour off, and the
fighter's own 0x15 spawn effect (5 words) and 0x16 play sound (3 words), which draw no colour.
While the colour is on, the model's material is blended to it by its alpha (ftmaterial.c
ftMaterial_800BF6BC: TEV stage CPREV x (1 - a) + colour x a, template ftMObj + 0x50).
The darkness scripts also turn on the overlay's light (0x0D with its enable bit clear): the fighter
is lit by an extra light of that colour (ftCo_09F4.c ftCo_8009F5AC), from the first step to the end.

    app/venv/Scripts/python.exe -B tools/liteaudit/hit_flash/build.py [--iso PATH] [--out PATH]

Writes app/frontend/src/tracker/replays/data/hitFlash.js:
  classes   [x158, x15C, x160]: the hitstun each knockback class starts at
  palette   ['rrggbbaa'] the colours the scripts reach
  anims     {colour animation: string}, one character per step (the state after that many steps):
            '.' no colour, else the palette index (ALPHABET)
  lights    {colour animation: 'rrggbb'}: the light those scripts turn on, on for every step
"""
import argparse
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[0:0] = [str(REPO / 'tools/liteaudit/item_shapes'), str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]

ANIMS = [4, 11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38]
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
MAX_STEPS = 600
HEADER = ("// The victim's body flash: the colour animations a hit starts (PlCo.dat ftLoadCommonData [6]),\n"
          "// stepped by the game's interpreter rule, by tools/liteaudit/hit_flash/build.py. Do not edit by\n"
          "// hand; see hitFlash.js.\n")


def f32(v):
    return struct.unpack('>f', struct.pack('>f', v))[0]


def u8(v):
    """(u8) of a float: truncated toward zero, low 8 bits"""
    return int(v) & 0xFF


def run(d, script):
    """The colour after each step of `script` (a DAT offset): [(r, g, b, a) or None], until the
    script is done or ends, and the light it turns on ('rrggbb' or None; it must stay on from the
    first step to the end); raises on a command the hit scripts do not use."""
    ptr, timer, stack = script, 0, []
    col, blend, on = [0.0] * 4, [0.0] * 4, False
    light_on, lit, light, lights = False, False, None, set()
    out = []
    for _ in range(MAX_STEPS):
        if ptr is not None and timer != 0:
            timer -= 1
        done = False
        while ptr is not None and timer == 0:
            w = d.u(ptr)
            op, arg = w >> 26, w & 0x3FFFFFF
            if op == 0:                                   # end: the script stops, the overlay stays
                ptr = None
            elif op == 3:                                 # loop start: count
                stack += [ptr + 4, arg]
                ptr += 4
            elif op == 4:                                 # loop end
                stack[-1] -= 1
                if stack[-1]:
                    ptr = stack[-2]
                else:
                    ptr += 4
                    del stack[-2:]
            elif op == 5:                                 # subroutine
                stack.append(ptr + 8)
                ptr = d.p(ptr + 4)
            elif op == 6:                                 # return
                ptr = stack.pop()
            elif op == 7:                                 # goto
                ptr = d.p(ptr + 4)
            elif op == 0x0A:                              # done: the overlay is cleared
                done = True
                break
            elif op == 0x0B:                              # wait
                timer += arg
                ptr += 4
            elif op == 0x0C:                              # colour and light off
                on = light_on = lit = False
                ptr += 4
            elif op == 0x0D:                              # light: rotation, enable bit, colour
                light_on = bool((w >> 25) & 1)
                lit, light = True, '%06x' % (d.u(ptr + 4) >> 8)
                ptr += 8
            elif op in (0x0E, 0x0F):                      # light colour / light blend
                ptr += 8
            elif op in (0x10, 0x11):                      # light rotation / light off
                if op == 0x11:
                    light_on = lit = False
                ptr += 4
            elif op == 0x12:                              # set colour
                c = d.u(ptr + 4)
                col = [float((c >> s) & 0xFF) for s in (24, 16, 8, 0)]
                blend, on = [0.0] * 4, True
                ptr += 8
            elif op == 0x13:                              # blend to a colour over `arg` steps
                c = d.u(ptr + 4)
                cur = [u8(v) for v in col]
                blend = [f32((0.5 + ((c >> s) & 0xFF) - cur[i]) / arg) for i, s in enumerate((24, 16, 8, 0))]
                ptr += 8
            elif op == 0x14:                              # colour off
                on = False
                ptr += 4
            elif op == 0x15:                              # spawn an effect on the fighter
                ptr += 20
            elif op == 0x16:                              # play a sound
                behaviour = (w >> 18) & 0xFF
                if behaviour <= 6:
                    ptr += 12
                elif 10 <= behaviour <= 15:
                    ptr += 8
                else:
                    raise SystemExit(f'sound behaviour {behaviour} at {ptr:#x}')
            else:
                raise SystemExit(f'command {op:#x} at {ptr:#x}')
        if done:
            break
        if on:
            col = [f32(v + b) for v, b in zip(col, blend)]
        if light_on:
            raise SystemExit(f'script {script:#x} turns its light on: hitFlash.js draws colour only')
        out.append(tuple(u8(v) for v in col) if on else None)
        lights.add(light if lit else None)
        if ptr is None and not on:
            break
    while out and out[-1] is None:
        out.pop()
    if len(lights) > 1:
        raise SystemExit(f'script {script:#x} turns its light on part of the time: hitFlash.js draws it for every step')
    return out, next(iter(lights), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--out', type=Path, default=DATA / 'hitFlash.js')
    args = ap.parse_args()
    import isofiles
    from isofiles import dat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(str(known_vanilla_iso()))
    isofiles.open_iso(args.iso)
    d = dat('PlCo.dat')
    root = d.root['ftLoadCommonData']
    cd, table = d.p(root), d.p(root + 6 * 4)
    classes = [round(d.f(cd + o), 3) for o in (0x158, 0x15C, 0x160)]
    if round(d.f(cd + 0x154), 3) != 0.4:
        raise SystemExit('PlCo x154 is not the hitstun factor 0.4: the classes would not be hitstun frames')
    palette, anims, lights = [], {}, {}
    for i in ANIMS:
        steps, light = run(d, d.p(table + 8 * i))
        if light:
            lights[str(i)] = light
        chars = []
        for c in steps:
            if c is None:
                chars.append('.')
                continue
            h = '%02x%02x%02x%02x' % c
            if h not in palette:
                palette.append(h)
            chars.append(ALPHABET[palette.index(h)])
        anims[str(i)] = ''.join(chars)
    if len(palette) > len(ALPHABET):
        raise SystemExit('palette too large')
    import json
    body = ('export default {\n  classes: ' + json.dumps(classes) + ',\n  palette: ' + json.dumps(palette) +
            ',\n  anims: {\n' + ''.join(f'    {k}: {json.dumps(v)},\n' for k, v in anims.items()) + '  },\n'
            '  lights: ' + json.dumps(lights) + ',\n}\n')
    args.out.write_text(HEADER + body, encoding='utf-8', newline='\n')
    print(f"{args.out.name}: classes {classes}, {len(palette)} colours, " +
          ', '.join(f'{k}: {len(v)} steps' for k, v in anims.items()) + f', {args.out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
