"""Do not confuse a buildable fighter with completed custom mechanics."""
import json
from fighter_port import port_receipt as receipt

def report(**extra):
    return dict(dict(fighter='example',route='own skeleton',own_states=['neutral'],
                     code=['neutral: projectile'],check=dict(ok=True)),**extra)

def test_custom_runtime_preserves_adaptations_and_unfinished_work():
    result=receipt.summarize(report(code=['neutral: projectile',
        'ADAPTATION: native capture pose','INCOMPLETE: wall sling'],
        special_numbers=dict(side=dict(limits=['source visual deferred']))))
    assert result['runtime']=='custom native code'
    assert result['features']==['neutral: projectile']
    assert result['limitations']==['INCOMPLETE: wall sling','source visual deferred']
    assert result['adaptations']==['ADAPTATION: native capture pose']
    assert result['generated_files_read_back'] is True
    assert result['gameplay_evidence']=='not assessed by this build receipt'

def test_template_and_partially_replaced_specials_stay_explicit():
    numbers=dict(neutral=[dict(what='PLAIN')],up=[dict(what='NOT BUILT')])
    partial=receipt.summarize(report(special_numbers=numbers))
    assert partial['runtime']=='custom code with unfinished special slots'
    assert partial['placeholder_specials']==['neutral'] and partial['missing_specials']==['up']
    template=receipt.summarize(report(specials_not_written='no custom adapter',special_numbers=numbers))
    assert template['runtime']=='animation and hitbox placeholders'
    assert 'no custom adapter' in template['limitations']

def test_readable_files_alone_do_not_imply_special_runtime():
    result=receipt.summarize(report(code=[],own_states=[]))
    assert result['runtime']=='special runtime not built'
    assert result['generated_files_read_back'] is True

def test_package_notes_are_portable_and_preserve_named_standins():
    members=receipt.package_members(report(code=['side: fireball (STAND-IN picture)']), 'Example')
    data=json.loads(members['port-implementation.json'])
    assert data['adaptations']==['side: fireball (STAND-IN picture)']
    assert 'Example' in members['PORT_NOTES.txt'].decode('utf-8')
    assert 'exact source parity' in members['PORT_NOTES.txt'].decode('utf-8')


def test_older_named_limit_notes_are_not_reported_as_implemented_features():
    note='Poison limitations: status visuals remain deferred'
    result=receipt.summarize(report(code=['Poison: attacks consume stacks',note]))
    assert result['features']==['Poison: attacks consume stacks']
    assert result['limitations']==[note]


def test_shared_article_program_receipts_keep_nested_limits_and_adaptations():
    projectile=dict(carried=[dict(id='shot',adaptations=['native reflection'])],
                    adaptations=['source model in rest pose'],limits=['compiled contact remains'])
    data=receipt.summarize(report(special_numbers=dict(projectiles=projectile)))
    assert data['adaptations']==['native reflection','source model in rest pose']
    assert data['limitations']==['compiled contact remains']
    old=receipt.summarize(report(special_numbers=dict(projectiles=[dict(adaptations=['world axes'])])))
    assert old['adaptations']==['world axes']
    custom=receipt.summarize(report(special_numbers=dict(side=[dict(what='shared',value=projectile)])))
    assert custom['adaptations']==data['adaptations']
