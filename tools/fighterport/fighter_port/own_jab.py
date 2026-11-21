"""Explicit source jab listeners, evaluated on the current input update.

Melee's enable_jab_followup command only opens a gate. Its toggle=1 is conditional
on a held item; it never closes the gate. The donor also has an unrelated early
input-buffer countdown. Neither represents an explicit source listener interval.
"""


def collect(profiles, actions):
    rows = []
    for profile in profiles:
        if 'jab_followup_windows' not in profile:
            continue
        for motion in profile['motions']:
            if motion not in ('Attack11', 'Attack12'):
                continue
            target = 'Attack12' if motion == 'Attack11' else 'Attack13'
            state = 44 if motion == 'Attack11' else 45
            windows = profile['jab_followup_windows']
            neutral = profile.get('jab_followup_neutral') or [False] * len(windows)
            if len(neutral) != len(windows):
                raise ValueError(f'{motion}: jab conditions and windows do not match')
            if windows and not any(a.motion == target and a.symbol for a in actions):
                raise ValueError(f'{motion}: source jab listener needs the missing {target} clip')
            for action in actions:
                if action.motion != motion:
                    continue
                if not windows:
                    rows.append(dict(action=action.index,state=state,first=1,end=1,target=state+1,neutral=False))
                for (first,end),quiet in zip(windows,neutral):
                    if not 1 <= first < end:
                        raise ValueError(f'{motion}: invalid jab interval {first}..{end}')
                    rows.append(dict(action=action.index,state=state,first=first,end=end,target=state+1,neutral=quiet))
    return rows


RUNTIME = '''
typedef struct {int action,state,first,end,target,neutral;} JabWindow;
static const JabWindow jab_windows[] = {
@rows@
};
static void (*jab_original[6])(GOBJ *);
static void Jab_Load(FighterData *fd)
{
    jab_original[fd->ply] = 0;
}
static void Jab_IASA(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int i;
    if (fd->flags.hitlag)
        return;
    // Disable the donor's independently timed buffer and latched gate, including stale early presses.
    fd->hitlag_mult = 0;
    fd->flags.x2218_2 = 0;
    fd->state_var.state_var1 = 0;
    for (i = 0; i < sizeof(jab_windows) / sizeof(jab_windows[0]); i++)
    {
        const JabWindow *w = &jab_windows[i];
        if (fd->action_id != w->action || fd->state_id != w->state ||
            fd->state.frame < w->first || fd->state.frame >= w->end || !(fd->input.down & HSD_BUTTON_A))
            continue;
        // Slap City InputValidator.InsideSegmentSC: AlmostNeutral uses strict NeutralMag (0.15).
        if (w->neutral && (fd->input.lstick.X <= -0.15f || fd->input.lstick.X >= 0.15f ||
                           fd->input.lstick.Y <= -0.15f || fd->input.lstick.Y >= 0.15f))
            continue;
        // Retail ftCo_Attack1.c initialization, including item pickup and state bookkeeping.
        if (w->target == 45)
            ((void (*)(GOBJ *))0x8008AE30)(gobj); // doAttack12
        else
            ((void (*)(GOBJ *))0x8008B194)(gobj); // doAttack13
        return;
    }
    if (jab_original[fd->ply])
        jab_original[fd->ply](gobj);
}
static void Jab_Frame(FighterData *fd)
{
    int i, applies = 0;
    for (i = 0; i < sizeof(jab_windows) / sizeof(jab_windows[0]); i++)
        if (fd->action_id == jab_windows[i].action && fd->state_id == jab_windows[i].state)
            applies = 1;
    if (applies)
    {
        if (fd->cb.IASA != Jab_IASA)
        {
            jab_original[fd->ply] = fd->cb.IASA;
            fd->cb.IASA = Jab_IASA;
        }
    }
    else if (fd->cb.IASA == Jab_IASA)
        fd->cb.IASA = jab_original[fd->ply];
}
'''


def source(rows):
    table = '\n'.join('    {'+', '.join(str(int(r[k])) for k in ('action','state','first','end','target','neutral'))+'},' for r in rows)
    return RUNTIME.replace('@rows@',table).splitlines()
