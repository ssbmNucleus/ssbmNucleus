"""Synthetic process/Win32 tests; never discover or move a real window."""
from tests.paths import BACKEND
import ctypes
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(BACKEND))
from shared.ingame import embed


@unittest.skipUnless(os.name == 'nt', 'Win32 presentation contract')
class CaptureTargetTests(unittest.TestCase):
    def setUp(self):
        self.process = SimpleNamespace(pid=321, poll=lambda: None)
        embed.set_active(321, process=self.process)
        self.discovery = patch.object(embed, '_capture_hwnd', return_value=555)
        self.discovery.start()

    def tearDown(self):
        self.discovery.stop()
        embed.clear_active()

    def test_retained_process_exposes_fresh_session_and_exact_handle(self):
        first = embed.capture_target()
        self.assertEqual(first['hwnd'], '555')
        self.assertEqual(first['pid'], 321)
        embed.set_active(321, process=self.process)
        self.assertNotEqual(first['sessionId'], embed.capture_target()['sessionId'])

    def test_target_carries_client_area_inside_captured_frame(self):
        from shared.ingame import screenshot_wgc
        # A Dolphin window: 31px title bar, 1px side borders, 642x512 compositor frame.
        with patch.object(screenshot_wgc, 'client_box', return_value=(1, 31, 640, 480, 642, 512)):
            self.assertEqual(embed.capture_target()['client'], {
                'x': 1, 'y': 31, 'width': 640, 'height': 480, 'frameWidth': 642, 'frameHeight': 512})
        with patch.object(screenshot_wgc, 'client_box', return_value=(1, 31, 640, 600, 642, 512)):
            self.assertIsNone(embed.capture_target()['client'])
        with patch.object(screenshot_wgc, 'client_box', side_effect=RuntimeError('minimized')):
            target = embed.capture_target()
        self.assertTrue(target['found'])
        self.assertIsNone(target['client'])

    def test_pid_without_process_is_not_capture_authority(self):
        embed.set_active(321)
        self.assertFalse(embed.capture_target()['found'])

    def test_exited_process_cannot_capture_reused_pid(self):
        self.process.poll = lambda: 0
        self.assertFalse(embed.capture_target()['found'])

    def test_replacement_during_discovery_is_rejected(self):
        def replace(_pid):
            embed.set_active(321, process=SimpleNamespace(pid=321, poll=lambda: None))
            return 555
        with patch.object(embed, '_capture_hwnd', side_effect=replace):
            self.assertFalse(embed.capture_target()['found'])

    def test_absent_render_does_not_mutate_any_window(self):
        with patch.object(embed, '_capture_hwnd', return_value=None), patch.object(embed, '_u32') as user32:
            self.assertFalse(embed.capture_target()['found'])
            user32.SetWindowPos.assert_not_called()

    def test_stale_session_and_arbitrary_handle_cannot_popout(self):
        target = embed.capture_target()
        with patch.object(embed, '_popout_hwnd') as popout:
            self.assertFalse(embed.present_capture('wrong', '555', 'separate')['found'])
            self.assertFalse(embed.present_capture(target['sessionId'], '666', 'separate')['found'])
            popout.assert_not_called()

    def test_popout_uses_exact_handle_under_session_lock(self):
        target = embed.capture_target()
        def popout(hwnd):
            self.assertEqual(hwnd, 555)
            self.assertTrue(embed._lock.locked())
            return {'found': True}
        with patch.object(embed, '_popout_hwnd', side_effect=popout):
            self.assertTrue(embed.present_capture(target['sessionId'], '555', 'separate')['found'])

    def test_handle_replaced_before_mutation_is_rejected(self):
        target = embed.capture_target()
        with patch.object(embed, 'capture_target', return_value=target), patch.object(embed, '_capture_hwnd', return_value=666), patch.object(embed, '_popout_hwnd') as popout:
            self.assertFalse(embed.present_capture(target['sessionId'], '555', 'separate')['found'])
            popout.assert_not_called()

    def test_behind_never_resizes_or_moves_graphics_error_dialog(self):
        from shared.ingame import screenshot_win
        target = embed.capture_target()
        calls = []
        def owner(_hwnd, out): out._obj.value = 999; return 1
        def rect(_hwnd, out): out._obj.left = 100; out._obj.top = 100; return 1
        def cls(hwnd, out, _length): out.value = '#32770' if hwnd == 777 else 'wxWindowNR'; return len(out.value)
        user32 = SimpleNamespace(GetWindowThreadProcessId=owner, GetWindowRect=rect, GetClassNameW=cls,
                                 SetWindowPos=lambda *args: calls.append(args) or 1)
        with patch.object(embed, '_u32', user32), patch.object(screenshot_win, '_pid_windows', return_value=[(555, '', 640, 480), (666, '', 640, 480), (777, '', 640, 480)]), patch.object(screenshot_win, '_child_count', return_value=14):
            self.assertTrue(embed.present_capture(target['sessionId'], '555', 'behind', '444', 999)['found'])
        self.assertEqual({c[0] for c in calls}, {555, 666})
        self.assertTrue(all(c[6] & embed.SWP_NOSIZE for c in calls))
        self.assertTrue(all(c[2] >= 0 and c[3] >= 0 for c in calls))

    def test_wrong_owner_window_pid_never_moves_target(self):
        target = embed.capture_target()
        with patch.object(embed, '_u32') as user32:
            user32.GetWindowThreadProcessId.return_value = 0
            self.assertFalse(embed.present_capture(target['sessionId'], '555', 'behind', '444', 999)['found'])
            user32.SetWindowPos.assert_not_called()


if __name__ == '__main__':
    unittest.main()
