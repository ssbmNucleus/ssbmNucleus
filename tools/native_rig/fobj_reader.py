"""Minimal FigaTree/FOBJ reader.

Read-only: decode, native_value, read_figatree.
Opcodes follow GXInterpolationType: 1 CON, 2 LIN, 3 SPL0, 4 SPL, 5 SLP, 6 KEY.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

# FOBJ number fields are LITTLE endian even though the containing DAT is big
# endian: the native parser assembles them byte-wise.  Reading them big endian
# leaves opcodes and frame clocks correct while every value is wrong, which is
# exactly what the raw-curves cross-check caught in audit-v1.
ENDIAN = "<"
FORMAT_CODE = {0: "f", 32: "h", 64: "H", 96: "b", 128: "B"}
FORMAT_NAME = {0: "float32", 32: "int16", 64: "uint16", 96: "int8", 128: "uint8"}
FORMAT_WIDTH = {0: 4, 32: 2, 64: 2, 96: 1, 128: 1}
OPCODE_NAME = {1: "CON", 2: "LIN", 3: "SPL0", 4: "SPL", 5: "SLP", 6: "KEY"}
CHANNEL_TYPE = {"rotateX": 1, "rotateY": 2, "rotateZ": 3,
                "translateX": 5, "translateY": 6, "translateZ": 7,
                "scaleX": 8, "scaleY": 9, "scaleZ": 10}
TYPE_CHANNEL = {v: k for k, v in CHANNEL_TYPE.items()}




def read_number(buf: bytes, cursor: int, flag: int):
    code = FORMAT_CODE[flag & 224]
    value = struct.unpack_from(ENDIAN + code, buf, cursor)[0]
    cursor += struct.calcsize(code)
    return (float(value) if code == "f" else float(value) / 2 ** (flag & 31)), cursor


def read_varint(buf: bytes, cursor: int):
    total = shift = 0
    while True:
        byte = buf[cursor]
        cursor += 1
        total |= (byte & 127) << shift
        if byte < 128:
            return total, cursor
        shift += 7
        if shift >= 35:
            raise ValueError("runaway varint")


def decode(buf: bytes, value_flag: int, slope_flag: int) -> list:
    """Decode one FOBJ buffer into its native event list."""
    cursor, clock, events = 0, 0, []
    while cursor < len(buf):
        word, cursor = read_varint(buf, cursor)
        op = word & 15
        if op == 0:
            break
        if op not in OPCODE_NAME:
            raise ValueError(f"unknown FOBJ opcode {op}")
        for _ in range((word >> 4) + 1):
            value = 0.0
            slope = 0.0
            step = 0
            if op != 5:
                value, cursor = read_number(buf, cursor, value_flag)
            if op in (4, 5):
                slope, cursor = read_number(buf, cursor, slope_flag)
            if op in (1, 2, 3, 4):
                step, cursor = read_varint(buf, cursor)
            events.append({"frame": clock, "value": value, "tan": slope, "op": op})
            clock += step
    return events


def native_value(events: list, frame: float) -> float:
    """Replay `fobj.c` state for one channel at one frame."""
    p0 = p1 = d0 = d1 = t0 = t1 = 0.0
    last, first = 0, True
    for event in events:
        op = event["op"]
        if op == 5:
            d0, d1 = d1, event["tan"]
            last = op
            continue
        if first:
            p1, d1, t1 = event["value"], event["tan"], float(event["frame"])
            last, first = op, False
            if frame <= t1:
                return p1
            continue
        p0, p1 = p1, event["value"]
        t0, t1 = t1, float(event["frame"])
        if op == 4:
            d0, d1 = d1, event["tan"]
        elif last != 5:
            d0, d1 = d1, 0.0
        if frame <= t1:
            if t1 == t0:
                return p1
            u = (frame - t0) / (t1 - t0)
            if last in (1, 6):
                return p0
            if last == 2:
                return p0 + (p1 - p0) * u
            return ((2 * u ** 3 - 3 * u ** 2 + 1) * p0 + (u ** 3 - 2 * u ** 2 + u) * (t1 - t0) * d0
                    + (-2 * u ** 3 + 3 * u ** 2) * p1 + (u ** 3 - u ** 2) * (t1 - t0) * d1)
        last = op
    return p1



@dataclass
class Track:
    node: int
    type: int
    value_flag: int
    slope_flag: int
    flag: int
    start: int
    length: int
    pointer: int
    events: list

    @property
    def channel(self) -> str:
        return TYPE_CHANNEL[self.type]

    @property
    def value_keys(self) -> int:
        return sum(1 for e in self.events if e["op"] != 5)




def read_figatree(data: bytes, root: int):
    """Node track counts and every decoded track of a FigaTree root."""
    frame_count = struct.unpack_from(">f", data, root + 8)[0]
    node_pointer, track_pointer = struct.unpack_from(">II", data, root + 12)
    counts = []
    while data[node_pointer + len(counts)] != 255:
        counts.append(data[node_pointer + len(counts)])
    tracks, index = [], 0
    for node, count in enumerate(counts):
        for _ in range(count):
            offset = track_pointer + 12 * index
            index += 1
            length, start, kind, vflag, sflag, flag, pointer = struct.unpack_from(
                ">HhBBBBI", data, offset)
            tracks.append(Track(node, kind, vflag, sflag, flag, start, length, pointer,
                                decode(data[pointer:pointer + length], vflag, sflag)))
    return frame_count, counts, tracks, track_pointer, node_pointer
