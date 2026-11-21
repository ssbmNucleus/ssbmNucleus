"""Independent raw walk: final block item sets, velocities and frame evidence.

Do not use stage_items for truth: it keeps ghosts when a rollback's final
emission no longer contains an item. Empty blocks must replace earlier sets.
"""
import math
import struct
from pathlib import Path
import common  # installs the backend import path without app startup
from tracker.store.slp_meta import HEADER, _parse_payload_sizes


def scan(path, detail=False):
    data = Path(path).read_bytes()
    if not data.startswith(HEADER) or len(data) < 17:
        raise ValueError("invalid Slippi header")
    rawlen = struct.unpack_from(">i", data, 11)[0]
    if rawlen <= 0:
        footer = data.rfind(b"U\x08metadata{", max(15, len(data) - 65536))
        rawlen = (footer if footer >= 0 else len(data)) - 15
    end = min(15 + rawlen, len(data))
    sizes, pos = _parse_payload_sizes(data)
    rows, post_rows, post_seen = [], [], set()
    frames, fod, stadium, cids = {}, {}, {}, {}
    version = (0, 0, 0)
    pending, pending_f, starts, first_port = None, None, False, None
    warnings, laser_events, latest, follower_posts = [], 0, None, 0
    if 15 + rawlen > len(data):
        warnings.append("raw block extends past EOF")
    i32 = lambda p: struct.unpack_from(">i", data, p)[0]
    f32 = lambda p: struct.unpack_from(">f", data, p)[0]
    while pos < end:
        cmd, p = data[pos], pos + 1
        size = sizes.get(cmd)
        if size is None or p + size > end:
            warnings.append(f"stopped at byte {pos}: unknown command or truncated payload")
            break
        if cmd == 0x36:
            version = tuple(data[p:p + 3])
        elif cmd == 0x3A and size >= 4 and version >= (2, 2, 0):
            starts = True
            pending_f, pending = i32(p), {}
            rows.append(pending_f)
        elif cmd == 0x38 and size >= 8 and data[p + 5]:
            follower_posts += 1
        elif cmd == 0x38 and size >= 8 and not data[p + 5]:
            fr, port, cid = i32(p), data[p + 4], data[p + 6]
            cids.setdefault(port, set()).add(cid)
            if first_port is None:
                first_port = port
            if port == first_port:
                post_rows.append(fr)
                post_seen.add(fr)
        elif cmd == 0x3B and size >= 37 and version >= (3, 0, 0):
            typ = struct.unpack_from(">H", data, p + 4)[0]
            laser_events += typ in (54, 55)
            if detail:
                fr, spawn, facing = i32(p), struct.unpack_from(">I", data, p + 33)[0], f32(p + 7)
                sample = {"spawn": spawn, "t": typ,
                          "o": struct.unpack_from(">b", data, p + 41)[0] if size >= 42 and version >= (3, 6, 0) else -1,
                          "s": data[p + 6], "d": 1 if facing > 0 else -1 if facing < 0 else 0}
                for key, off in (("vx", 11), ("vy", 15), ("x", 19), ("y", 23)):
                    value = f32(p + off)
                    sample[key] = value if math.isfinite(value) else None
                if starts:
                    if fr == pending_f and pending is not None:
                        pending[spawn] = sample
                else:
                    frames.setdefault(fr, {})[spawn] = sample
        elif cmd == 0x3C and size >= 4:
            fr = i32(p)
            if detail and pending is not None and pending_f == fr:
                frames[fr] = pending
                pending, pending_f = None, None
            if size >= 8:
                latest = i32(p + 4)
        elif detail and cmd == 0x3F and size >= 9 and version >= (3, 18, 0):
            fr, plat, height = i32(p), data[p + 4], f32(p + 5)
            fod[(fr, plat)] = [fr, plat, height if math.isfinite(height) else None]
        elif detail and cmd == 0x41 and size >= 8 and version >= (3, 18, 0):
            fr, ev, tid = struct.unpack_from(">iHH", data, p)
            stadium[fr] = [fr, ev, tid]
        pos = p + size
    if detail and pending is not None:
        warnings.append(f"unclosed final item block at frame {pending_f}; not treated as truth")
    if not starts:
        rows = post_rows
    unique = sorted(set(rows))
    backward = [a - b for a, b in zip(rows, rows[1:]) if b < a]
    result = {"version": list(version), "rows": len(rows), "unique_frames": len(unique),
              "first_frame": unique[0] if unique else None, "last_frame": unique[-1] if unique else None,
              "rollback_rows": len(rows) - len(unique),
              "rollback_fraction": (len(rows) - len(unique)) / max(1, len(rows)),
              "backward_jumps": len(backward), "max_rewind": max(backward, default=0),
              "missing_frames": unique[-1] - unique[0] + 1 - len(unique) if unique else 0,
              "chars_internal": sorted({cid for ids in cids.values() for cid in ids}),
              "transforms": any({7, 19} <= ids for ids in cids.values()),
              "laser_events": laser_events, "follower_posts": follower_posts,
              "latest_finalized": latest, "warnings": warnings}
    if detail:
        tracks, live = [], {}
        for fr in sorted(frames):
            for spawn, sample in sorted(frames[fr].items()):
                tr = live.get(spawn)
                if tr is None or tr["t"] != sample["t"] or tr["start"] + len(tr["x"]) != fr:
                    tr = {k: sample[k] for k in ("spawn", "t", "o")}
                    tr.update(start=fr, **{k: [] for k in ("x", "y", "d", "s", "vx", "vy")})
                    tracks.append(tr)
                    live[spawn] = tr
                for key in ("x", "y", "d", "s", "vx", "vy"):
                    tr[key].append(sample[key])
        result.update(row_fids=rows, frame_ids=sorted(post_seen), items=tracks,
                      item_block_frames=sorted(frames),
                      stage={"fod": [fod[k] for k in sorted(fod)],
                             "stadium": [stadium[k] for k in sorted(stadium)]})
    return result
