import pytest
from echo_rivals2 import gamedata
from echo_rivals2.branches import branch_stem


def test_separate_aerial_attack_owns_its_timing_and_branches():
    assert gamedata.MOVES['NspecialAir'][0] == ('main','d00specialairn')
    att={'AerialAnimation':{'ObjectPath':'/Characters/Air.0'}}
    assert gamedata.aerial_part('Nspecial',att,'main','d00specialn',True) is None
    assert gamedata.aerial_part('NspecialAir',att,'main','d00specialairn') is None


def test_declared_aerial_animation_is_used_for_whole_and_conditional_parts():
    att={'AerialAnimation':{'ObjectPath':'/Actual/Nonstandard_Name.0'}}
    assert gamedata.aerial_part('Fspecial',att,'main','d01specials') == ('d01specialairs','/Actual/Nonstandard_Name')
    stem=branch_stem('Nspecial','Throw Startup')
    assert gamedata.aerial_part('Nspecial',att,'Throw Startup',stem) == (
        branch_stem('NspecialAir','Throw Startup'),'/Actual/Nonstandard_Name')
    assert gamedata.aerial_part('Dspecial',att,'main','d03speciallw')[0]=='d03specialairlw'
    assert gamedata.aerial_part('Nspecial',{},'main','d00specialn') is None


def test_compiled_only_mechanics_keep_their_clips_without_becoming_default_paths():
    def window(name,next='',cancels=()):
        return dict(StringTableKey=name,NextWindowStringTableKey=next,WindowLengthFrames=10,
                    WindowCancels=[dict(PostCancelWindowStringTableKey=c) for c in cancels])
    # The tongue hits and sling are dispatched by compiled game behavior.
    att=dict(Windows=[window('Startup','Whiff'),window('Whiff'),
        window('Hit Ground','Consume'),window('Hit Air','Consume'),window('Consume','Recovery'),
        window('Recovery'),window('Sling','Sling Recovery'),window('Sling Recovery'),
        window('Special Fall')])
    main=[('main','d01specials')]
    parts=gamedata.parts_with_branches('Fspecial',att,main)
    roots=[name for name,_ in parts]
    assert roots==['main','Hit Ground','Hit Air','Sling']
    assert [w['StringTableKey'] for w in gamedata.path_from(att,'Startup')]==['Startup','Whiff']
    covered={w['StringTableKey'] for name,_ in parts for w in gamedata.path_from(att,'Startup' if name=='main' else name)}
    assert covered=={w['StringTableKey'] for w in att['Windows']} - {'Special Fall'}
    assert all(stem==branch_stem('Fspecial',name) for name,stem in parts[1:])
    # Disconnected loops also terminate extraction and retain an explicit path_end.
    att['Windows'] += [window('Loop A','Loop B'),window('Loop B','Loop A')]
    assert len(gamedata.parts_with_branches('Fspecial',att,main))==5
