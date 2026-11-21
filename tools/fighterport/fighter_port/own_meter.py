"""A resource number anchored to each player's native match HUD.

Uses the match's font/camera and a native text GObj, including its normal scene
destruction. Each generated fighter module owns only its text objects.
"""
import json,re

RUNTIME='''
static void @read@(FighterData *,int *,int *);
typedef struct {Text *text; GOBJ *owner; int kind,sub,value,mode;} PortMeter;
static PortMeter port_meter[6];
static void Meter_Destroy(void *data)
{
    int i;
    for (i=0;i<6;i++)
        if (port_meter[i].text == data)
        {
            port_meter[i].text = 0;
            port_meter[i].owner = 0;
        }
    // Preserve the text library's native userdata destructor and linked-list removal.
    Text_DestroyAllAlloc((Text *)data);
}
static void Meter_Update(GOBJ *gobj)
{
    Text *text = gobj->userdata;
    int i,value,mode;
    for (i=0;i<6;i++)
    {
        PortMeter *m = &port_meter[i];
        FighterData *fd;
        Vec3 *pos;
        if (m->text != text) continue;
        if (!m->owner || Fighter_GetGObj(i) != m->owner ||
            ((FighterData *)m->owner->userdata)->kind != m->kind)
        {
            Text_Destroy(text);
            return;
        }
        fd = m->owner->userdata;
        text->hidden = fd->flags.sleep || stc_matchhud->element_data[i].is_hidden;
        pos = Match_GetPlayerHUDPos(i);
        // SIS glyphs use a downward Y axis. Position the viewport in HUD units;
        // scaling individual subtexts leaves the default 32-unit baseline unscaled.
        text->trans.X = pos->X+3.0f;
        text->trans.Y = -pos->Y-8.0f;
        @read@(fd,&value,&mode);
        if (value != m->value)
        {
            Text_SetText(text,m->sub,@format@,value);
            m->value = value;
        }
        if (mode != m->mode)
        {
            GXColor white = {255,255,255,255};
            GXColor buy = {112,255,144,255};
            GXColor sell = {255,216,96,255};
            Text_SetColor(text,m->sub,mode == 1 ? &buy : mode == 2 ? &sell : &white);
            m->mode = mode;
        }
        return;
    }
}
static int Meter_Canvas(void)
{
    TextCanvas *c;
    int index = 0;
    // Share an existing match-HUD canvas, including one made by another port module.
    // No canvas or font is destroyed by a fighter; the scene owns those shared objects.
    for (c=*stc_textcanvas_first;c;c=c->next)
        if (c->sis_idx == 2)
        {
            if (!c->cam_gobj && c->p_link == 15 && c->gx_link == 11 && c->gx_pri == 0)
                return index;
            index++;
        }
    return Text_CreateCanvas(2,(int)stc_matchhud->cam_gobj,14,15,0,11,0,19);
}
static void Meter_Load(FighterData *fd)
{
    if (port_meter[fd->ply].text)
        Text_Destroy(port_meter[fd->ply].text);
}
static void Meter_Frame(FighterData *fd,GOBJ *owner)
{
    PortMeter *m;
    Text *text;
    if (fd->ply < 0 || fd->ply >= 6 || Fighter_GetGObj(fd->ply) != owner) return;
    m = &port_meter[fd->ply];
    if (m->text || !stc_matchhud->cam_gobj || !stc_sis_data[2]) return;
    text = Text_CreateText(2,Meter_Canvas());
    m->text = text; m->owner = owner; m->kind = fd->kind;
    m->value = -2147483647; m->mode = -1;
    text->align = 1; text->kerning = 1;
    m->sub = Text_AddSubtext(text,0,0,@format@,0);
    text->viewport_scale.X = text->viewport_scale.Y = 0.05f;
    // Text_CreateText already installed its userdata; replace only its destructor,
    // then delegate that exact native cleanup in Meter_Destroy.
    text->gobj->destructor_function = (int)Meter_Destroy;
    GObj_AddProc(text->gobj,Meter_Update,17);
    Meter_Update(text->gobj);
}
'''

def source(read, label):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',read):
        raise ValueError('meter reader must be a C identifier')
    # Other ASCII punctuation is interpreted as the first byte of a Shift-JIS pair,
    # consuming the following character. In particular, "$30" displays just "0".
    if not re.fullmatch(r'''[A-Za-z0-9 .,:'"-]*''',label):
        raise ValueError('meter label contains characters unsupported by the native font converter')
    return RUNTIME.replace('@read@',read).replace('@format@',json.dumps(label+'%d')).splitlines()
