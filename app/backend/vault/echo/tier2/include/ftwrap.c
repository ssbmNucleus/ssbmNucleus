// ftwrap.c -- a per-frame hook that runs AFTER the state's physics and BEFORE
// hit detection, for every COMMON action state (jab, tilts, smashes, Fall...).
//
// Why: the m-ex OnFrame slot runs at the top of the fighter think proc, before
// the animation step that executes subaction commands, so a hitbox created this
// frame is invisible to it until hit detection has already used it. The state's
// physics callback (Fighter_procUpdate) runs after that step. Common states live
// in the shared ftData_MotionStateList (0x803C2800, 341 x 0x20), which
// Fighter_Init assigns to fd->ftstates_common BEFORE the character's OnLoad, so
// OnLoad can copy the table into this file, route every physics_callback
// through FtWrap_Phys and point fd->ftstates_common at the copy. Callbacks are
// cached per state at ActionStateChange, so install at load, never later.
//
//   FtWrap_Install(fd, Moves_PostPhysics);   // in OnLoad, after the donor's OnLoad

#define FTWRAP_COMMON_MAX 341

__attribute__((used, section(".data"))) static FtState ftwrap_common[FTWRAP_COMMON_MAX] = { [0] = { 0 } };
__attribute__((used, section(".data"))) static FtState *ftwrap_orig = (FtState *)1;
__attribute__((used, section(".data"))) static void (*ftwrap_hook)(GOBJ *) = (void (*)(GOBJ *))1;

void FtWrap_Phys(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int id = fd->state_id;
    // DOL / MEM1 pointers are NEGATIVE as signed ints -- compare unsigned.
    if ((unsigned int)ftwrap_orig > 1u && id >= 0 && id < FTWRAP_COMMON_MAX)
    {
        void (*cb)(GOBJ *) = ftwrap_orig[id].physics_callback;
        if (cb != 0)
            cb(gobj);
    }
    if ((unsigned int)ftwrap_hook > 1u)
        ftwrap_hook(gobj);
}

void FtWrap_Install(FighterData *fd, void (*hook)(GOBJ *))
{
    FtState *orig = fd->ftstates_common;
    if (orig == 0 || orig == ftwrap_common)
        return;
    if ((unsigned int)ftwrap_orig <= 1u)
    {
        memcpy(ftwrap_common, orig, sizeof(FtState) * FTWRAP_COMMON_MAX);
        for (int i = 0; i < FTWRAP_COMMON_MAX; i++)
            ftwrap_common[i].physics_callback = FtWrap_Phys;
        ftwrap_orig = orig;
    }
    ftwrap_hook = hook;
    fd->ftstates_common = ftwrap_common;
}

// The original callbacks of a common state, for chaining from a replacement.
FtState *FtWrap_Original(int state_id)
{
    if ((unsigned int)ftwrap_orig > 1u && state_id >= 0 && state_id < FTWRAP_COMMON_MAX)
        return &ftwrap_orig[state_id];
    return 0;
}
