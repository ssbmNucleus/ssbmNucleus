from types import SimpleNamespace
import pytest
from echo_slapcity import gamedata as slap
from echo_rivals2 import gamedata as rivals
from fighter_port import combat, own_rivals_articles, oneshot
from fighter_port.combat_values import shield_bonus, shield_field
from vault.echo.commands import BY_KEY
from vault.echo.subactions import FighterDat, read_bits
from test_own_route import FROZEN, ORDER, game_of, hit, route
from test_own_slap_projectiles import fixture as slap_projectile
from test_rivals_article_programs import fixture as rivals_article


@pytest.mark.parametrize('multiplier,expected',[(0,-12),(.5,-6),(1,0),(1.5,6),(2,12)])
def test_slap_effective_damage_and_shield_multiplier_reach_native_signed_script(multiplier,expected):
    rd=slap.Reader(None,{'swing':dict(dmg=10,dmgmult=1.2,shielddmg=multiplier)},
        dict(unit=1,armature_scale=1,shortcuts={}),1)
    source=rd.hitbox(dict(p='swing',r=2),4,1)
    assert source['damage']==12 and source['shield_damage']==expected
    source.update(bone='top',last=6)
    game=game_of([source])
    table={'c00attack11':[dict(target_motion='Attack11',id='c00attack11-attack11',time_keys=None,offset=0)]}
    spec,_=oneshot.combat_spec(game,table,'Marth',route.rig_stub(FROZEN),1,{'Attack11':30},route.OwnPlacer(ORDER),{})
    entries=combat.compile_move(spec['moves'][0])
    hit_entry=next(entry for entry in entries if entry[0]==BY_KEY['create_hitbox'].code)
    assert hit_entry[1]['damage']==12 and hit_entry[1]['shield_damage']==expected
    raw,_=FighterDat.encode_script([hit_entry])
    field=BY_KEY['create_hitbox'].param('shield_damage')
    assert field.signed and read_bits(raw,field.bit_offset,field.bits)==expected & 255


@pytest.mark.parametrize('multiplier,expected',[(.5,-5),(1,0),(1.2,2),(2,10)])
def test_rivals_body_and_article_hit_readers_preserve_shield_multiplier(multiplier,expected):
    _,source=rivals_article()
    prop=source['HitboxOnHitProperties'][0]
    prop.update(Damage=10,AdvancedOnHitProperties=dict(ShieldDamageMultiplier=multiplier))
    rd=SimpleNamespace(unit=.1,offset=lambda *a:('top',[0,0,0]))
    part=rivals.Part(source,rivals.path_from(source,'Launch'),'d01specials')
    rows=rivals.hitbox_rows(rd,source,part,None)
    assert rows[0]['shield_damage']==pytest.approx(expected)
    data=rivals.article(SimpleNamespace(default=lambda pkg:source),'shot',rd)
    assert data['hit']['shield_damage']==pytest.approx(expected)
    item,_=own_rivals_articles.build(data,'shot',dict(folder='shot'),1,entry='Launch')
    native=next(h for phase in item['states'] for _,h in phase if h)
    assert native['damage']==10 and native['shield_damage']==expected


@pytest.mark.parametrize('multiplier,expected',[(0,-5),(.4,-3),(1,0),(2,5),(100,127)])
def test_slap_projectile_uses_same_signed_native_field_and_safe_bounds(multiplier,expected):
    builder=slap_projectile()
    builder.game['projectiles']['shot']['atkprop']['shielddmg']=multiplier
    builder.spec('shot')
    fields=builder.items[0]['states'][1][0][1]
    assert fields['damage']==5 and fields['shield_damage']==expected
    # Uses the same first five packed words as the native item command.
    raw,_=FighterDat.encode_script([(BY_KEY['create_hitbox'].code,
        {k:v for k,v in fields.items() if k not in ('again','group')},None)])
    field=BY_KEY['create_hitbox'].param('shield_damage')
    assert read_bits(raw,field.bit_offset,field.bits)==expected & 255


def test_shield_conversion_is_bounded_finite_and_default_is_unchanged():
    assert shield_field(None)==shield_field(shield_bonus(12))==0
    assert shield_bonus(-1,0)==0
    assert shield_field(-999)==-128 and shield_field(999)==127
    assert shield_field(-2.4)==-2 and shield_field(2.4)==2
    for value in (True,'2',float('nan'),float('inf')):
        with pytest.raises(ValueError):shield_field(value)
        with pytest.raises(ValueError):shield_bonus(12,value)
    with pytest.raises(ValueError):shield_bonus(12,-1)
    for value in (-129,128):
        profile=dict(total=10,phases=[dict(start=4,end=6,hitboxes=[dict(bone=0,position=[0,0,0],
            radius=2,damage=10,angle=45,kbg=30,bkb=20,shield_damage=value)])])
        with pytest.raises(ValueError):combat.compile_move(profile)
