// hud.c -- an on-screen text line from fighter code, on Melee's debug text
// system (DevText / m-ex "DevelopText"), which is alive in every scene and
// draws through its own ortho camera. One line per fighter instance; the
// DevText pointer lives in fighter_var slot 49 (0x22EC) so it survives state
// changes. Verified in-match 2026-09-03 (tier2/README.md).
//
//   HUD_Create(fd, x, y, w, h)          -> in OnLoad (x/y in screen pixels, w/h in characters)
//   HUD_Printf(fd, "STANCE %d", a, b)   -> whenever the text should change (2 int args)
//
// Engine facts: DevText_Create(id, x, y, w, h, buf) takes a caller-owned
// buffer of w*h*2 bytes (+ slack); DevText_Show(devtext_gobj @ 0x804D6E1C,
// text) attaches it to the global draw list; cursor off via DevText_HideCursor
// @ 0x80302AB0 (byte +0x26 also carries show_bg -- never zero it wholesale).
// m-ex link names: DevelopText_CreateDataTable / _Activate / _EraseAllText /
// _ResetCursorXY / _AddString (= DevText_Printf @ 0x80302D4C) / _HideBG /
// _StoreTextScale.

#define HUD_VAR fighter_var.ft_var49
#define HUD_DEVTEXT_ID 40   // vanilla debug displays use 6..12

static GOBJ **hud_devtext_gobj = (GOBJ **)0x804D6E1C;

void HUD_Create(FighterData *fd, int x, int y, int w, int h)
{
    if (fd->HUD_VAR != 0 || *hud_devtext_gobj == 0)
        return;
    u8 *buf = HSD_MemAlloc(w * h * 2 + 0x80);
    DevText *t = DevelopText_CreateDataTable(HUD_DEVTEXT_ID + fd->ply, x, y, w, h, buf);
    if (t == 0)
        return;
    DevelopText_Activate(*hud_devtext_gobj, t);
    DevelopText_HideBG(t);
    ((void (*)(DevText *))0x80302AB0)(t);   // DevText_HideCursor (not in melee.link)
    DevelopText_StoreTextScale(t, 12.0f, 16.0f);
    fd->HUD_VAR = (int)t;
}

void HUD_Printf(FighterData *fd, char *fmt, int a, int b)
{
    DevText *t = (DevText *)fd->HUD_VAR;
    if (t == 0)
        return;
    DevelopText_EraseAllText(t);
    DevelopText_ResetCursorXY(t, 0, 0);
    DevelopText_AddString(t, fmt, a, b);
}
