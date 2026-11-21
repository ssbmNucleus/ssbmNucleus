"""Native resource HUD ownership, changed values and independent player slots."""
from pathlib import Path
import os,shutil,subprocess
import pytest
from fighter_port import own_meter as meter,code

HEADER='''#include <assert.h>
#include <string.h>
#include <stdarg.h>
typedef struct GOBJ GOBJ;
typedef struct {float X,Y,Z;} Vec3;
typedef struct {int ply,kind;struct {int sleep;} flags;} FighterData;
typedef struct {unsigned char r,g,b,a;} GXColor;
struct GOBJ {void *userdata; int destructor_function;};
typedef struct {GOBJ *gobj; int align,kerning,hidden;Vec3 trans,viewport_scale;} Text;
typedef struct TextCanvas {struct TextCanvas *next; GOBJ *cam_gobj;int sis_idx,p_link,gx_link,gx_pri;} TextCanvas;
static struct {GOBJ *cam_gobj;struct {int is_hidden;} element_data[6];} hud;
#define stc_matchhud (&hud)
static void *stc_sis_data[5];
static TextCanvas canvas={0,0,2,15,11,0},*canvas_first=&canvas,**stc_textcanvas_first=&canvas_first;
static Text texts[6];static GOBJ text_gobjs[6],*players[6];static Vec3 positions[6];
static int creates,canvases,destroys,writes,colors,registers,last_value;
static float last_x,last_y;
static void Meter_Destroy(void *);
GOBJ *Fighter_GetGObj(int i){return players[i];}
Vec3 *Match_GetPlayerHUDPos(int i){return &positions[i];}
void Text_DestroyAllAlloc(Text *t){destroys++;}
void Text_Destroy(Text *t){Meter_Destroy(t);}
void Text_SetPosition(Text *t,int sub,float x,float y){last_x=x;last_y=y;}
void Text_SetText(Text *t,int sub,char *fmt,...){va_list a;va_start(a,fmt);last_value=va_arg(a,int);va_end(a);writes++;}
void Text_SetColor(Text *t,int sub,GXColor *c){colors++;}
int Text_CreateCanvas(int font,int parent,int cls,int pl,int pp,int gx,int gp,int cp){canvases++;canvas_first=&canvas;return 0;}
Text *Text_CreateText(int font,int id){int n=creates++%6;assert(font==2 && id==0);texts[n].gobj=&text_gobjs[n];text_gobjs[n].userdata=&texts[n];return &texts[n];}
int Text_AddSubtext(Text *t,float x,float y,char *fmt,...){return 0;}
void Text_SetScale(Text *t,int sub,float x,float y){}
void GObj_AddProc(GOBJ *g,void (*fn)(GOBJ *),int p){assert(p==17);registers++;}
'''
READ='''static int amount[6],mode[6];
static void ReadMeter(FighterData *f,int *v,int *m){*v=amount[f->ply];*m=mode[f->ply];}
'''
MAIN='''int main(void){
FighterData f[2]={0};GOBJ g[2]={{&f[0]},{&f[1]}};Text *first;
f[0].kind=27;f[1].kind=27;f[1].ply=1;players[0]=&g[0];players[1]=&g[1];
positions[0].X=-12;positions[0].Y=-20;
Meter_Load(&f[0]);Meter_Frame(&f[0],&g[0]);assert(!creates);
hud.cam_gobj=&g[0];Meter_Frame(&f[0],&g[0]);assert(!creates);
stc_sis_data[2]=&canvas;Meter_Frame(&f[0],&g[0]);
assert(creates==1 && registers==1 && canvases==0 && writes==1 && last_value==0);
first=port_meter[0].text;
assert(first->trans.X==-9 && first->trans.Y==12 && first->viewport_scale.X==0.05f);
Meter_Frame(&f[0],&g[0]);Meter_Update(first->gobj);assert(creates==1 && writes==1 && colors==1);
amount[0]=400;mode[0]=2;Meter_Update(first->gobj);assert(writes==2 && last_value==400 && colors==2);
// Text runs after contacts and independently of the fighter's hitlag animation callback.
amount[0]=0;Meter_Update(first->gobj);assert(writes==3 && last_value==0);
hud.element_data[0].is_hidden=1;Meter_Update(first->gobj);assert(first->hidden);
hud.element_data[0].is_hidden=0;f[0].flags.sleep=1;Meter_Update(first->gobj);assert(first->hidden);
f[0].flags.sleep=0;Meter_Update(first->gobj);assert(!first->hidden);
amount[1]=1000;Meter_Frame(&f[1],&g[1]);assert(creates==2 && port_meter[1].text!=first);
Meter_Load(&f[0]);assert(destroys==1 && !port_meter[0].text && port_meter[1].text);
Meter_Frame(&f[0],&g[0]);assert(creates==3);
// Owner removal/replacement destroys only its own text, without reading freed fighter data.
players[0]=0;Meter_Update(port_meter[0].text->gobj);assert(destroys==2 && !port_meter[0].text);
f[1].kind=9;Meter_Update(port_meter[1].text->gobj);assert(destroys==3 && !port_meter[1].text);
players[0]=&g[0];canvas_first=0;Meter_Frame(&f[0],&g[0]);assert(canvases==1);
// Native scene text destruction clears the registration before allocation reuse.
Meter_Destroy(port_meter[0].text);assert(destroys==4 && !port_meter[0].text && !port_meter[0].owner);
Meter_Load(&f[0]);Meter_Frame(&f[0],&g[0]);assert(creates==5 && canvases==1);
return 0;}
'''

def test_resource_meter_ownership_updates_and_scene_cleanup(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    (tmp_path/'meter.c').write_text(HEADER+'\n'.join(meter.source('ReadMeter','Cash '))+READ+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
            'cl /nologo /TC /std:c11 meter.c /Fe:meter.exe\nif errorlevel 1 exit /b 1\nmeter.exe\nexit /b %errorlevel%\n')
        r=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'meter'
        r=subprocess.run([cc,'-std=c11',str(tmp_path/'meter.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert r.returncode==0,r.stdout+r.stderr
        r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stdout+r.stderr

def test_meter_compiles_with_native_kit():
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('requires MexTK')
    tier2=pytest.importorskip('vault.echo.tier2.build')
    own=dict(source=meter.source('ReadMeter','Cash ')+[
        'static void ReadMeter(FighterData *f,int *v,int *m){*v=0;*m=0;}'],
        load=['Meter_Load(fd);'],frame=['Meter_Frame(fd,gobj);'],provides=[],table=[])
    files,_=code.source('Marth',onload=0x801364AC,own=own)
    result=tier2.check_files(files,mextk_dir=str(kit))
    assert result.get('ok'),result.get('error')

def test_meter_arguments_cannot_inject_code_or_format_directives():
    for reader,label in [('f()','Cash '),('Read','%s'),('Read','Cash\n'),('Read','Cash $')]:
        with pytest.raises(ValueError):meter.source(reader,label)
