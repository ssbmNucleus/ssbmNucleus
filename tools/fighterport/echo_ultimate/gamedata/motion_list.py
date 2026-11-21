"""Reader for a fighter's motion_list.bin: per motion, its script names, its
animation file, and the frame on which the move can be cancelled into another.

Layout worked out from Shulk's file (the jab 1 record) and checked by parsing
the whole file with no bytes left over; `bytes_left` must be 0.
"""
import struct
from pathlib import Path

from .prc import hash40


def read(path, names=()):
    b = Path(path).read_bytes()
    labels = {hash40(n): n for n in names}

    def lab(h):
        return labels.get(h, f'0x{h:010x}')

    magic, list_id, count = struct.unpack_from('<QQQ', b, 0)
    o = 24
    out = []
    for _ in range(count):
        motion, game = struct.unpack_from('<QQ', b, o)
        flags, blend, n_anim, size = struct.unpack_from('<HBBI', b, o + 16)
        o += 24
        anims = list(struct.unpack_from(f'<{n_anim}Q', b, o))
        o += 8 * n_anim
        o += (n_anim + 3) // 4 * 4            # one byte per animation, padded to 4
        # `size` counts what follows: the other script names, then (fighters only) four bytes. A fighter has
        # three names (expression, sound, effect: size 28); a weapon's list has two and no tail (size 16).
        if n_anim == 0 and size % 8 not in (0, 4):
            size = 28                                   # a fighter's empty record: the field is not a length
        n_hash, tail = size // 8, size % 8
        hashes = list(struct.unpack_from(f'<{n_hash}Q', b, o))
        o += 8 * n_hash
        xlu_start, xlu_end, cancel, no_stop = struct.unpack_from('<4B', b, o) if tail == 4 else (0, 0, 0, 0)
        o += tail
        out.append({'motion': lab(motion), 'game': lab(game), 'flags': flags, 'blend_frames': blend,
                    'animations': [lab(a) for a in anims], 'scripts': [lab(x) for x in hashes],
                    'intangible_start': xlu_start, 'intangible_end': xlu_end, 'cancel_frame': cancel,
                    'no_stop_intp': no_stop})
    return {'count': count, 'bytes_left': len(b) - o, 'motions': out}

