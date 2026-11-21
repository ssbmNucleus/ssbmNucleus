"""The list a port is finished against, and the one command that runs a port's stages."""
from types import SimpleNamespace

import pytest

from fighter_port import port


def test_the_checklist_is_numbered_lines_by_section():
    rows = port.lines()
    ids = [r['id'] for r in rows]
    assert len(ids) == len(set(ids)) and ids[0] == '1.1'
    assert all(r['text'] and r['section'] for r in rows)
    # a bullet's indented lines belong to it; headings without a number are not part of the list
    assert any(r['id'] == '6.10' and 'For a counter' in r['text'] for r in rows)
    assert not any('fighter_port.port' in r['text'] for r in rows)


def test_the_optional_fidelity_checklist_preserves_answers_and_differences(tmp_path):
    rows = port.lines()
    assert len(port.unanswered(tmp_path)) == len(rows)
    port.record(tmp_path, '1.1', 'done', 'seen standing beside the donor')
    port.record(tmp_path, '1.10', 'difference', 'the cape is stiff')
    assert len(port.unanswered(tmp_path)) == len(rows) - 2
    assert [d['id'] for d in port.differences(tmp_path)] == ['1.10']
    with pytest.raises(ValueError):                     # an answer says how it is known
        port.record(tmp_path, '1.2', 'done', '  ')
    with pytest.raises(ValueError):
        port.record(tmp_path, '1.2', 'probably', 'looked fine')
    with pytest.raises(ValueError):
        port.record(tmp_path, '99.1', 'done', 'no such line')


def test_a_line_looked_at_and_not_finished_is_open_and_still_owed(tmp_path):
    rows = port.lines()
    port.record(tmp_path, '1.1', 'done', 'seen standing beside the donor')
    port.record(tmp_path, '1.2', 'open', 'the three team costumes are named in the roster entry; not seen in a team match')
    # open is a recorded state, not an answer: the line is still unanswered, and its note is kept
    assert 'open' not in port.ANSWERS and port.answers(tmp_path)['1.2']['answer'] == 'open'
    assert len(port.unanswered(tmp_path)) == len(rows) - 1 and '1.2' in [r['id'] for r in port.unanswered(tmp_path)]
    looked = port.open_lines(tmp_path)
    assert [r['id'] for r in looked] == ['1.2'] and 'not seen in a team match' in looked[0]['how'] and looked[0]['line']
    assert port.differences(tmp_path) == []
    with pytest.raises(ValueError):                     # it says what is owed
        port.record(tmp_path, '1.3', 'open', '')
    port.record(tmp_path, '1.2', 'done', 'seen in a team match, red, blue and green')      # ... and can be closed
    assert port.open_lines(tmp_path) == [] and len(port.unanswered(tmp_path)) == len(rows) - 2


def test_one_stage_alone_or_a_run_of_them_can_be_asked_for():
    order = port.OWN_STAGES
    assert port.chosen(order) == list(order)
    assert port.chosen(order, only='preflight') == ['preflight'] and port.chosen(order, only='driver') == ['driver']
    assert port.chosen(order, start='driver', to='costumes') == ['driver', 'sounds', 'costumes']
    assert port.chosen(order, to='prepare') == ['preflight', 'project', 'prepare']
    assert port.chosen(order, start='art') == ['art', 'build']
    for wrong in (dict(only='model'), dict(start='model'), dict(to='model')):     # a stage of the other route is refused by name
        with pytest.raises(SystemExit, match='not a stage of this route'):
            port.chosen(order, **wrong)
    with pytest.raises(SystemExit):                     # --only is one stage: neither --from nor --to goes with it
        port.chosen(order, start='driver', only='driver')
    with pytest.raises(SystemExit):
        port.chosen(order, start='costumes', to='driver')
    with pytest.raises(SystemExit, match='not a stage of this route'):
        port.chosen(port.STAGES, start='prepare')       # (this used to mean "from the first" and ran everything)


def _stub_run(tmp_path, monkeypatch, **more):
    """`port.run` with every stage a one-line script: 'driver' fails, the rest say their name."""
    import sys
    (tmp_path / 'repo' / 'app' / 'backend').mkdir(parents=True)
    work = tmp_path / 'work'
    a = SimpleNamespace(**dict(dict(fighter='wolf', game='ultimate', donor='Marth', name='Wolf', work=str(work), root='R',
                                    body=None, iso=None, mextk=None, repo=str(tmp_path / 'repo'), start=None, to=None,
                                    only=None, rip=None, own=True, tests=None, allow_large=False), **more))
    monkeypatch.setattr(port, 'commands', lambda _a: {
        s: [[sys.executable, '-c', f"import sys; print('this is {s}'); sys.exit({1 if s == 'driver' else 0})"]]
        for s in port.OWN_STAGES})
    said = []
    return a, work, said, port.run(a, log=said.append)


def test_only_runs_that_stage_and_preflight_is_said_aloud(tmp_path, monkeypatch):
    a, work, said, status = _stub_run(tmp_path, monkeypatch, only='preflight')
    assert status['ran'] == ['preflight'] and list(status['stages']) == ['preflight'] and status['stages']['preflight']['ok']
    # what preflight found is printed by the command itself, not only left in its log
    assert any('this is preflight' in line for line in said) and (work / 'tmp' / 'port-preflight.log').exists()
    # the stages after it are owed, which is not a failure of this run
    assert status['owed']['stages'] == [s for s in port.stage_order(a) if s != 'preflight']


def test_to_stops_after_a_stage_and_a_failure_stops_the_run(tmp_path, monkeypatch):
    a, work, said, status = _stub_run(tmp_path, monkeypatch, to='prepare')
    assert status['ran'] == ['preflight', 'project', 'prepare'] and not any('this is project' in line for line in said)
    a, work, said, status = _stub_run(tmp_path / 'second', monkeypatch, start='prepare', to='costumes')
    assert status['ran'] == ['prepare', 'driver'] and not status['stages']['driver']['ok']        # sounds never ran
    assert 'sounds' not in status['stages'] and any('driver: FAILED' in line for line in said)


def test_the_status_tells_open_lines_from_lines_never_looked_at(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    port.record(work, '1.2', 'open', 'not seen in a team match')
    a, work, said, status = _stub_run(tmp_path, monkeypatch, only='preflight', calibrate=True)
    owed = status['owed']
    assert owed['checklist lines open'] == 1 and owed['open'] == ['1.2 not seen in a team match']
    assert owed['checklist lines unanswered'] == len(port.lines())           # the open one is among them
    assert any('1 recorded open' in line for line in said)


def test_the_stages_run_in_an_order_each_can_stand_on():
    a = SimpleNamespace(fighter='ike', game='brawl', donor='Marth', name='Ike', work='W', root='R', body='B.dat', iso='out.iso',
                        mextk='M', repo=None, start='project', rip='rip.zip')
    plan = port.commands(a)
    # everything that can be known in seconds is asked first, on both routes
    assert port.STAGES[0] == port.OWN_STAGES[0] == 'preflight'
    assert plan['preflight'][0][1:4] == ['-m', 'fighter_port.preflight', 'ike'] and '--own' not in plan['preflight'][0]
    assert plan['preflight'][0][plan['preflight'][0].index('--game') + 1] == 'brawl'
    # the driver reads the donor's package and the project's executable: the project comes first
    assert port.STAGES == ('preflight', 'model', 'project', 'driver', 'sounds', 'costumes', 'build', 'verify', 'round') and set(plan) == set(port.STAGES)
    assert plan['driver'][0][1:4] == ['-m', 'fighter_port.oneshot', 'ike'] and '--game' in plan['driver'][0]
    assert plan['costumes'][0][1].endswith('brawl_recolors.py') and plan['costumes'][0][-2:] == ['B.dat', 'rip.zip']
    # the rip is made ready for the importer first: what is hidden at rest taken out, the eye's layers named
    assert plan['model'][0][1].endswith('brawl_model.py') and plan['model'][0][-1].endswith('ike-ready.zip')
    assert port.commands(SimpleNamespace(**dict(vars(a), game='ultimate')))['costumes'][0][1].endswith('ultimate_recolors.py')
    assert plan['build'][0][-1] == 'out.iso'


def test_a_fighter_on_its_own_skeleton_has_stages_of_its_own():
    from pathlib import Path
    a = SimpleNamespace(fighter='duckhunt', game='ultimate', donor='Marth', name='Duck Hunt', work='W', root='R', body=None,
                        iso='out.iso', mextk='M', repo=None, start=None, rip=None, own=True)
    plan = port.commands(a)
    assert set(plan) == set(port.OWN_STAGES) and port.OWN_STAGES[:3] == ('preflight', 'project', 'prepare')
    ask = plan['preflight'][0]
    assert ask[1:4] == ['-m', 'fighter_port.preflight', 'duckhunt'] and '--own' in ask and ask[ask.index('--mextk') + 1] == 'M'
    assert ask[ask.index('--iso') + 1] == 'out.iso' and '--allow-large' not in ask
    # a costume too large for a match stops the costumes stage unless the command is told to build it all the same
    assert '--allow-large' not in plan['costumes'][0]
    large = port.commands(SimpleNamespace(**dict(vars(a), allow_large=True)))
    assert large['costumes'][0][-1] == '--allow-large' and '--allow-large' in large['preflight'][0]
    driver = plan['driver'][0]
    assert driver[1:4] == ['-m', 'fighter_port.oneshot', 'duckhunt'] and driver[driver.index('--own') + 1] == 'W'
    # nothing is imported: the body comes from the game's own files, so no stage asks for one
    assert not any('--body' in argv for stage in plan.values() for argv in stage)
    # each disc starts from a fresh project; the first is only to take the artwork's pictures from
    assert [Path(argv[1]).name for argv in plan['firstdisc']] == ['make_project.py', 'package_build.py']
    assert plan['firstdisc'][1][-1].endswith('first.iso')
    # the game is started once: the round boots the first disc, and the artwork is cut from the round's pictures
    assert Path(plan['round'][0][1]).name == 'round.py' and plan['round'][0][3] == plan['firstdisc'][1][-1]
    assert '--shots' in plan['art'][0] and not any(str(x).endswith('.iso') for x in plan['art'][0])
    assert port.OWN_STAGES.index('verify') < port.OWN_STAGES.index('round') < port.OWN_STAGES.index('art') < port.OWN_STAGES.index('build')
    assert [Path(argv[1]).name for argv in plan['build'][:2]] == ['make_project.py', 'package_build.py'] and plan['build'][1][-1] == 'out.iso'
    assert plan['build'][2][1:3] == ['-m', 'fighter_port.verify'] and '--art-later' not in plan['build'][2]     # the files, artwork and all


def test_default_build_never_launches_a_calibration_harness_or_builds_a_test_disc(tmp_path, monkeypatch):
    a, work, said, status = _stub_run(tmp_path, monkeypatch, start='costumes')
    assert status['ran'] == ['costumes','build','verify']
    assert status['owed']['stages'] == list(port.stage_order(a)[:5])
    assert not {'firstdisc','round','art'} & set(port.stage_order(a))
    assert status['calibration_requested'] is False
    assert status['checklist_scope'] == 'optional fidelity backlog'
    assert status['owed']['checklist lines unanswered'] > 0
    assert not any('fidelity backlog' in message for message in said)


def test_explicit_calibration_and_legacy_stage_requests_remain_available(tmp_path, monkeypatch):
    a, work, said, status = _stub_run(tmp_path, monkeypatch, start='firstdisc', calibrate=True)
    assert status['ran'] == ['firstdisc','verify','round','art','build']
    assert status['calibration_requested'] is True
    assert port.stage_order(SimpleNamespace(own=False)) == port.STAGES[:-1]
    assert 'art' not in port.stage_order(SimpleNamespace(own=True), forms=True)
    for flag in ('start','to','only'):
        assert port.calibration_requested(SimpleNamespace(**{flag:'art'}))
    assert port.calibration_requested(SimpleNamespace(tests=['upb']))


def test_normal_file_verification_includes_packager_generated_art():
    a=SimpleNamespace(fighter='ranno',game='rivals2',donor='Marth',name='Ranno',work='W',root='R',
                      body=None,iso='out.iso',mextk=None,own=True)
    assert '--art-later' not in port.commands(a)['verify'][0]
    a.calibrate=True
    assert '--art-later' in port.commands(a)['verify'][0]


def test_explicit_test_disc_request_does_not_start_a_harness(tmp_path, monkeypatch):
    a, work, said, status = _stub_run(tmp_path, monkeypatch, only='firstdisc')
    assert status['ran'] == ['firstdisc']
    assert status['calibration_requested'] is False
    assert 'round' not in port.stage_order(a)



def test_regenerating_inputs_cannot_reuse_an_old_successful_build_or_verifier(tmp_path, monkeypatch):
    import json
    work=tmp_path/'work'
    (work/'port').mkdir(parents=True)
    previous={name:dict(ok=True,log='previous-'+name) for name in port.OWN_STAGES}
    (work/'port/status.json').write_text(json.dumps(dict(stages=previous)))
    a,work,said,status=_stub_run(tmp_path,monkeypatch,only='driver')
    assert not status['stages']['driver']['ok']
    assert {'sounds','build','verify'} <= set(status['owed']['stages'])
    assert status['stages']['build']['log']=='previous-build'
    assert status['stages']['build']['stale'] and status['stages']['build']['invalidated_by']=='driver'
    assert 'costumes' not in status['owed']['stages']  # Frozen body/rig wasn't regenerated.
    a.only='verify'
    status=port.run(a,log=lambda _:None)
    assert port.stage_current(status['stages'],'verify')
    assert not port.stage_current(status['stages'],'build')
    assert 'build' in status['owed']['stages']  # Checking loose files doesn't rebuild a stale disc.


def test_running_stage_is_saved_before_process_start_and_readonly_checks_preserve_artifacts(tmp_path, monkeypatch):
    import json
    a,work,said,status=_stub_run(tmp_path,monkeypatch,only='preflight')
    status['stages'].update(build=dict(ok=True),verify=dict(ok=True))
    status['implementation']={'current_driver':True}
    status_path=work/'port/status.json';status_path.write_text(json.dumps(status))
    a.only='preflight'
    status=port.run(a,log=lambda _:None)
    assert port.stage_current(status['stages'],'build') and port.stage_current(status['stages'],'verify')
    def interrupted(*args,**kwargs):
        pending=json.loads(status_path.read_text())
        assert pending['stages']['sounds']['running']
        assert 'implementation' not in pending
        assert {'sounds','build','verify'} <= set(pending['owed']['stages'])
        assert not port.stage_current(pending['stages'],'build')
        raise RuntimeError('interrupted writer')
    monkeypatch.setattr(port.subprocess,'run',interrupted)
    a.only='sounds'
    with pytest.raises(RuntimeError,match='interrupted writer'):port.run(a,log=lambda _:None)
    pending=json.loads(status_path.read_text())
    assert not port.stage_current(pending['stages'],'sounds')
    assert not port.stage_current(pending['stages'],'verify')



@pytest.mark.parametrize('verify_fails',[False,True])
def test_build_embedded_verification_counts_only_after_success(tmp_path,monkeypatch,verify_fails):
    import json,sys
    a,work,said,status=_stub_run(tmp_path,monkeypatch,only='preflight')
    status['stages']['verify']=dict(ok=True,log='old-verifier')
    (work/'port/status.json').write_text(json.dumps(status))
    plan=port.commands(a)
    plan['build'].append([sys.executable,'-m','fighter_port.verify',str(work)])
    monkeypatch.setattr(port,'commands',lambda _:plan)
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=int(verify_fails and argv[1:3]==['-m','fighter_port.verify']))
    monkeypatch.setattr(port.subprocess,'run',run)
    a.only='build';status=port.run(a,log=lambda _:None)
    assert calls[-1][1:3]==['-m','fighter_port.verify']
    assert port.stage_current(status['stages'],'build') is not verify_fails
    assert port.stage_current(status['stages'],'verify') is not verify_fails
    if not verify_fails:assert status['stages']['verify']['performed_by']=='build'


def test_driver_failure_cannot_present_old_implementation_as_current(tmp_path,monkeypatch):
    import json
    work=tmp_path/'work';(work/'port').mkdir(parents=True)
    report=dict(fighter='duckhunt',route='own skeleton',code=['custom specials'],own_states=['state'])
    (work/'port/report.json').write_text(json.dumps(report))
    a,work,said,status=_stub_run(tmp_path,monkeypatch,only='driver')
    assert not status['implementation']['current_driver']
    assert any('awaiting a successful driver rebuild' in message for message in said)
    assert not any('special runtime: custom native code' in message for message in said)
