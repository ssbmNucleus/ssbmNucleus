"""Portable, read-only fake MEM1 regressions; no Dolphin or assets required."""
import json
import struct
import unittest

from shared.ingame.pose import CaptureError, capture_pose, capture_visibility


class Memory:
    def __init__(self):
        self.data = bytearray(0x10000)
        self.reads = []

    def put(self, address, fmt, *values):
        struct.pack_into('>' + fmt, self.data, address - 0x80000000, *values)

    def bytes(self, address, size):
        self.reads.append((address, size))
        offset = address - 0x80000000
        return bytes(self.data[offset:offset+size])


class PoseTests(unittest.TestCase):
    def setUp(self):
        self.d = Memory()
        self.ft, self.parts, self.joint = 0x80001000, 0x80004000, 0x80005000
        self.d.put(self.ft+0x5e8, 'I', self.parts)
        self.d.put(self.parts, 'II', self.joint, 0)
        self.d.put(self.joint+0x1c, '4f', 1, 2, 3, 99)
        self.d.put(self.joint+0x2c, '3f', 1, 2, 3)
        self.d.put(self.joint+0x38, '3f', 4, 5, 6)
        self.d.put(self.joint+0x44, '12f', *range(12))
        self.d.put(self.ft+0x894, 'f', 0.123456789)

    def test_correct_xyz_and_raw_time_no_memory_writes(self):
        before = bytes(self.d.data)
        pose = capture_pose(self.d, self.ft, 1, secondary=True)
        joint = pose['joints'][0]
        self.assertEqual(joint['rotation_xyz'], [1, 2, 3])
        self.assertEqual(joint['rotation_xyzw'], [1, 2, 3, 99])
        self.assertEqual(joint['world'], list(range(12)))
        self.assertEqual(joint['translation'], [4, 5, 6])
        self.assertEqual(joint['rotation_kind'], 'euler_xyz')
        self.assertIsNone(joint['overlay'])
        self.assertIsNone(joint['aobj_frame'])
        self.assertNotEqual(pose['anim_frame_raw'], round(pose['anim_frame_raw'], 2))
        self.assertEqual(before, bytes(self.d.data))

    def test_secondary_quaternion_and_zero_aobj_time(self):
        second, aobj = 0x80006000, 0x80007000
        self.d.put(self.parts+4, 'I', second)
        self.d.put(second+0x14, 'I', 0x20000)
        self.d.put(second+0x1c, '4f', 0, 0, 0, 1)
        self.d.put(second+0x7c, 'I', aobj)
        overlay = capture_pose(self.d, self.ft, 1, secondary=True)['joints'][0]['overlay']
        self.assertEqual(overlay['rotation_kind'], 'quaternion_xyzw')
        self.assertEqual(overlay['rotation_xyzw'], [0, 0, 0, 1])
        self.assertEqual(overlay['aobj_frame'], 0)

    def test_unused_w_is_preserved_as_bits_and_json_safe(self):
        self.d.put(self.joint+0x28, 'I', 0x7fc00001)
        joint = capture_pose(self.d, self.ft, 1)['joints'][0]
        self.assertIsNone(joint['rotation_xyzw'][3])
        self.assertEqual(joint['rotation_words'][3], 0x7fc00001)
        json.dumps(joint, allow_nan=False)
        self.d.put(self.joint+0x14, 'I', 0x20000)
        with self.assertRaises(CaptureError):
            capture_pose(self.d, self.ft, 1)

    def test_dirty_cache_is_reported_without_recomputing_or_accepting_it(self):
        for flags, expected in ((0x40, True), (0x20, False), (0x20040, True)):
            self.d.put(self.joint+0x14, 'I', flags)
            before = bytes(self.d.data)
            joint = capture_pose(self.d, self.ft, 1)['joints'][0]
            self.assertIs(joint['matrix_dirty'], expected)
            self.assertEqual(joint['world'], list(range(12)))
            self.assertEqual(bytes(self.d.data), before)

    def test_invalid_secondary_pointer_is_not_missing(self):
        self.d.put(self.parts+4, 'I', 0x817ffffc)
        with self.assertRaises(CaptureError):
            capture_pose(self.d, self.ft, 1, secondary=True)

    def test_required_pointer_short_read_and_counts_fail(self):
        for pointer in (0, 0x80005001, 0x81800000, 0x80020000):
            self.d.put(self.parts, 'I', pointer)
            with self.assertRaises(CaptureError):
                capture_pose(self.d, self.ft, 1)
        for count in (0, -1, 4097, True):
            with self.assertRaises(CaptureError):
                capture_pose(self.d, self.ft, count)

    def test_visibility_uses_real_count_byte_order_and_masks(self):
        table, obj = 0x80008000, 0x80009000
        self.d.put(self.ft+0x5ec, 'II', 1, table)
        self.d.put(table, 'I', obj)
        self.d.put(obj+0x14, 'I', 1)
        self.d.put(self.ft+0x5f4, 'BB', 255, 1)
        self.d.put(self.ft+0x221d, 'BB', 0x20, 0x04)
        before = bytes(self.d.data)
        data = capture_visibility(self.d, self.ft, expected_count=1)
        self.assertEqual(data['states'][0], {'prev_raw': 255, 'idx_raw': 1})
        self.assertTrue(data['model_override'])
        self.assertTrue(data['whole_model_invisible'])
        self.assertTrue(data['objects'][0]['hidden'])
        self.assertEqual(before, bytes(self.d.data))
        self.d.put(self.ft+0x221d, 'BB', 0x04, 0x20)
        data = capture_visibility(self.d, self.ft)
        self.assertFalse(data['model_override'])
        self.assertFalse(data['whole_model_invisible'])
        with self.assertRaises(CaptureError):
            capture_visibility(self.d, self.ft, expected_count=115)

    def test_empty_visibility_and_corrupt_count(self):
        self.assertEqual(capture_visibility(self.d, self.ft)['objects'], [])
        self.d.put(self.ft+0x5ec, 'I', 0xffffffff)
        with self.assertRaises(CaptureError):
            capture_visibility(self.d, self.ft)

    def test_unresolved_fighter_is_an_explicit_capture_failure(self):
        for pointer in (None, 0, 0x817ffffc):
            with self.assertRaises(CaptureError):
                capture_pose(self.d, pointer, 1)
            with self.assertRaises(CaptureError):
                capture_visibility(self.d, pointer)


if __name__ == '__main__':
    unittest.main()
