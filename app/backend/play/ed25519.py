"""
Ed25519 signature checking (RFC 8032, section 5.1.7), verification only, in plain Python.

The app's signed release feed (electron/updates/updater.js, signed by tools/build/release_to_r2.py
with ``openssl pkeyutl -sign -rawin``) is Ed25519 over the canonical JSON of the manifest. Play's
client feed uses the same key and the same signed form (play/client_feed.py); this is the check on
the backend's side. Nothing here holds or makes a secret, so it needs no constant-time arithmetic,
and it needs no compiled module: the installer ships none for it (docs/dev/WINDOWS_SIGNING.md).

The checks are the RFC's own, made strict where the RFC leaves room:

  * the public key and R must decode to points on the curve (y < p, a square root exists, and
    x = 0 never comes with the sign bit set);
  * S must be below the group order L (no malleable second form of a signature);
  * [S]B = R + [k]A, compared as points (cofactorless, as OpenSSL and Node check it).

tests/backend/test_play_client_feed.py checks it against the RFC's test vectors and against
pycryptodome's Ed25519 on random keys and messages, and that every changed bit is refused.
"""

import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _add(a, b):
    """Two points in extended coordinates (X, Y, Z, T), x = X/Z, y = Y/Z, xy = T/Z."""
    k = (a[1] - a[0]) * (b[1] - b[0]) % _P
    m = (a[1] + a[0]) * (b[1] + b[0]) % _P
    c = 2 * a[3] * b[3] * _D % _P
    d = 2 * a[2] * b[2] % _P
    e, f, g, h = m - k, d - c, d + c, m + k
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _times(scalar, point):
    out = (0, 1, 1, 0)                      # the neutral element
    while scalar > 0:
        if scalar & 1:
            out = _add(out, point)
        point = _add(point, point)
        scalar >>= 1
    return out


def _same(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _decode(raw):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_BASE = (_GX, _GY, 1, _GX * _GY % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is the Ed25519 signature of `message` by `public_key` (32 raw bytes)."""
    if not isinstance(public_key, (bytes, bytearray)) or not isinstance(signature, (bytes, bytearray)):
        return False
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    a = _decode(bytes(public_key))
    if a is None:
        return False
    r_raw = bytes(signature[:32])
    r = _decode(r_raw)
    if r is None:
        return False
    s = int.from_bytes(signature[32:], 'little')
    if s >= _L:
        return False
    k = int.from_bytes(hashlib.sha512(r_raw + bytes(public_key) + bytes(message)).digest(), 'little') % _L
    return _same(_times(s, _BASE), _add(r, _times(k, a)))


#: The DER prefix of an Ed25519 SubjectPublicKeyInfo (RFC 8410): what `openssl pkey -pubout` writes.
_SPKI_PREFIX = bytes.fromhex('302a300506032b6570032100')


def public_key_from_pem(text: str) -> bytes:
    """The 32 raw bytes of an Ed25519 public key in PEM (SubjectPublicKeyInfo). Raises ValueError."""
    import base64
    lines = [line.strip() for line in str(text).strip().splitlines()]
    if not lines or lines[0] != '-----BEGIN PUBLIC KEY-----' or lines[-1] != '-----END PUBLIC KEY-----':
        raise ValueError('not a PEM public key')
    der = base64.b64decode(''.join(lines[1:-1]), validate=True)
    if len(der) != len(_SPKI_PREFIX) + PUBLIC_KEY_BYTES or not der.startswith(_SPKI_PREFIX):
        raise ValueError('not an Ed25519 public key')
    key = der[len(_SPKI_PREFIX):]
    if _decode(key) is None:
        raise ValueError('not a point on Ed25519')
    return key
