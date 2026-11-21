"""mexcli.commands: the one MexCLI spawn, its JSON parsing and its exit-code report."""
import subprocess

import mexcli.commands


def test_mexcli_parse_json_handles_indented_output_with_noise():
    noisy = "Trimmed Image 80 64\nTrimmed Image 24 24\n{\n  \"success\": true,\n  \"seriesId\": 17\n}"
    assert mexcli.commands.parse_json(noisy) == {'success': True, 'seriesId': 17}
    assert mexcli.commands.parse_json('{"a": 1}') == {'a': 1}
    assert mexcli.commands.parse_json('not json at all') == {}
    assert mexcli.commands.parse_json('') == {}


def test_mexcli_parse_json_first_brace_reads_from_the_first_brace():
    # The rule project.py's Diet stock-icon pass has always used.
    assert mexcli.commands.parse_json('log line {"a": 1}', first_brace=True) == {'a': 1}
    assert mexcli.commands.parse_json('log line {"a": 1}') == {}
    assert mexcli.commands.parse_json('no json here', first_brace=True) == {}


def test_mexcli_run_json_stringifies_args_and_reports_the_exit_code(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 3, stdout='log\n{"success": false}', stderr='')

    monkeypatch.setattr(mexcli.commands.subprocess, 'run', fake_run)
    bank = tmp_path / 'bank.ssm'
    assert mexcli.commands.run_json(['ssm-info', bank, 7]) == {'success': False, '_returncode': 3}
    argv, kwargs = calls[0]
    assert argv == [str(mexcli.commands.MEXCLI), 'ssm-info', str(bank), '7']
    assert kwargs['capture_output'] is True and kwargs['text'] is True
    assert kwargs['check'] is False
    assert kwargs['cwd'] == str(mexcli.commands.config.PROJECT_ROOT)
    assert mexcli.commands.run_json(['get-costumes'], first_brace=True, returncode=False) == {'success': False}
