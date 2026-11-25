"""core/child_env.py: the one filter between the backend's environment and a program it starts."""
import sys

from tests.paths import BACKEND

sys.path.insert(0, str(BACKEND))

from core.child_env import child_environment, is_private  # noqa: E402

BASE = {
    'PATH': r'C:\Windows', 'SYSTEMROOT': r'C:\Windows', 'TEMP': r'C:\t',
    'NUCLEUS_BACKEND_TOKEN': 'backend-secret', 'NUCLEUS_UI_APPROVAL_KEY': 'window-secret',
    'NUCLEUS_DATA_ROOT': r'C:\data', 'nucleus_lowercase': 'x',
    'OPENROUTER_API_KEY': 'provider', 'GITHUB_TOKEN': 'gh', 'SOME_SECRET': 's',
    'PYTHONPATH': r'C:\app\backend', 'PYTHONHOME': r'C:\py',
    '_PYI_APPLICATION_HOME_DIR': r'C:\t\_MEI1', '_MEIPASS2': r'C:\t\_MEI1',
}


def test_nucleus_settings_secrets_and_the_apps_python_path_are_left_out():
    env = child_environment(BASE)
    assert env == {'PATH': r'C:\Windows', 'SYSTEMROOT': r'C:\Windows', 'TEMP': r'C:\t'}


def test_the_same_packaged_program_keeps_its_frozen_variables_only():
    env = child_environment(BASE, same_program=True, python=True)
    assert env['_PYI_APPLICATION_HOME_DIR'] and env['_MEIPASS2']
    assert env['PYTHONUNBUFFERED'] == '1' and env['PYTHONIOENCODING'] == 'utf-8'
    assert not [k for k in env if k.upper().startswith('NUCLEUS_') or k.endswith(('_TOKEN', '_API_KEY'))]


def test_a_caller_can_hand_one_back_on_purpose_and_drop_more():
    env = child_environment(BASE, extra={'NUCLEUS_BACKEND_TOKEN': 'for-the-callback', 'PORT': 5000},
                            unset=('temp',))
    assert env['NUCLEUS_BACKEND_TOKEN'] == 'for-the-callback' and env['PORT'] == '5000'
    assert 'TEMP' not in env
    assert is_private('nucleus_ui_approval_key') and not is_private('PATH')
