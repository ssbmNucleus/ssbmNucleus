"""The app window's own key (core/ui_channel.py), for tests that call a route
only the window may call -- the way the window does.

    from tests.backend.window_key import WINDOW, as_the_window  # noqa: F401
    pytestmark = pytest.mark.usefixtures('as_the_window')

    client.post(route, headers=WINDOW, json=body)
"""
import pytest

UI_KEY = 'window-only-test-key'
WINDOW = {'X-Nucleus-UI-Key': UI_KEY}


@pytest.fixture
def as_the_window(monkeypatch):
    """This backend has a window key (Electron hands it one at launch)."""
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    return dict(WINDOW)
