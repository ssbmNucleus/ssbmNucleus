"""Dev evals take the OpenRouter key from the environment (or an op:// ref in .env); nothing is stored."""
import types

import pytest

import runner


def test_plain_env_var_short_circuits_everything(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'sk-or-env')
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('op invoked despite env var'))
    assert runner.load_api_key() == 'sk-or-env'


def test_op_reference_in_env_file_is_resolved_via_op(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('OPENROUTER_API_KEY= op://<vault>/<item>/OPENROUTER_API_KEY\n', encoding='utf-8')
    monkeypatch.setattr(runner, 'ENV_PATH', str(env))
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return types.SimpleNamespace(stdout='sk-or-fresh\n')
    monkeypatch.setattr('subprocess.run', fake_run)
    assert runner.load_api_key() == 'sk-or-fresh'
    assert len(calls) == 1


def test_unresolved_op_reference_in_env_does_not_short_circuit(tmp_path, monkeypatch):
    """`op run` leaves the raw ref in the environment when it cannot resolve it."""
    env = tmp_path / '.env'
    env.write_text('OPENROUTER_API_KEY=sk-or-from-file\n', encoding='utf-8')
    monkeypatch.setattr(runner, 'ENV_PATH', str(env))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'op://<vault>/<item>/OPENROUTER_API_KEY')
    assert runner.load_api_key() == 'sk-or-from-file'


def test_unset_key_fails_with_clear_message(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'ENV_PATH', str(tmp_path / 'missing.env'))
    with pytest.raises(RuntimeError, match='OPENROUTER_API_KEY is not set'):
        runner.load_api_key()
