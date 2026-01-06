from __future__ import annotations

import hashlib
import secrets
from typing import Tuple

# Finite field and group parameters for Ed25519
_q = 2**255 - 19
_l = 2**252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, -1, _q) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _inv(z: int) -> int:
    return pow(z, _q - 2, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1) % _q
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


def _edwards_add(P: Tuple[int, int], Q: Tuple[int, int]) -> Tuple[int, int]:
    (x1, y1) = P
    (x2, y2) = Q
    denom = _inv(1 + _d * x1 * x2 * y1 * y2 % _q)
    x3 = ((x1 * y2 + x2 * y1) * denom) % _q
    denom_y = _inv(1 - _d * x1 * x2 * y1 * y2 % _q)
    y3 = ((y1 * y2 + x1 * x2) * denom_y) % _q
    return x3, y3


def _scalarmult(P: Tuple[int, int], e: int) -> Tuple[int, int]:
    Q = (0, 1)
    while e > 0:
        if e & 1:
            Q = _edwards_add(Q, P)
        P = _edwards_add(P, P)
        e >>= 1
    return Q


def _isoncurve(P: Tuple[int, int]) -> bool:
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


_Bx = 15112221349535400772501151409588531511454012693041857206046113283949847762202
_By = 46316835694926478169428394003475163141307993866256225615783033603165251855960
_B = (_Bx % _q, _By % _q)


def _encodepoint(P: Tuple[int, int]) -> bytes:
    x, y = P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decodepoint(s: bytes) -> Tuple[int, int]:
    if len(s) != 32:
        raise ValueError("point encoding must be 32 bytes")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x_sign = (s[31] >> 7) & 1
    x = _xrecover(y)
    if x & 1 != x_sign:
        x = _q - x
    P = (x, y)
    if not _isoncurve(P):
        raise ValueError("point not on curve")
    return P


def _clamp_scalar(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = hashlib.sha512(seed).digest()
    a_bytes = bytearray(h[:32])
    a_bytes[0] &= 248
    a_bytes[31] &= 63
    a_bytes[31] |= 64
    a = int.from_bytes(a_bytes, "little")
    prefix = h[32:]
    return a, prefix


def derive_public_key(seed: bytes) -> bytes:
    a, _ = _clamp_scalar(seed)
    A = _scalarmult(_B, a)
    return _encodepoint(A)


def generate_keypair() -> tuple[bytes, bytes]:
    seed = secrets.token_bytes(32)
    return seed, derive_public_key(seed)


def sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _clamp_scalar(seed)
    public_key = derive_public_key(seed)
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _l
    R = _scalarmult(_B, r)
    R_enc = _encodepoint(R)
    hram = hashlib.sha512(R_enc + public_key + message).digest()
    k = int.from_bytes(hram, "little") % _l
    S = (r + k * a) % _l
    return R_enc + S.to_bytes(32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> None:
    if len(signature) != 64:
        raise ValueError("signature must be 64 bytes")
    R_bytes = signature[:32]
    S_bytes = signature[32:]
    S = int.from_bytes(S_bytes, "little")
    if S >= _l:
        raise ValueError("signature scalar out of range")
    A = _decodepoint(public_key)
    R = _decodepoint(R_bytes)
    k = int.from_bytes(hashlib.sha512(R_bytes + public_key + message).digest(), "little") % _l
    left = _scalarmult(_B, S)
    right = _edwards_add(R, _scalarmult(A, k))
    if left != right:
        raise ValueError("invalid signature")
